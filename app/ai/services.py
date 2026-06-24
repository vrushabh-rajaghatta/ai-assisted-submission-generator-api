"""
Main AI service for processing documents and managing AI-assisted content extraction.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.ai.models import (
    AIExtractionResult, 
    SectionMapping, 
    DocumentContent, 
    ContentSuggestion,
    AIProcessingRequest,
    AIProcessingResponse
)
from app.ai.document_parser import document_parser
from app.ai.content_mapper import content_mapper
from app.ai.sarvam_service import sarvam_ai_service
from app.ai.logging_utils import AILogger
from app.dossier.models import DossierSection
from app.files.models import UploadedFile


class AIProcessingService:
    """Main service for AI-powered document processing and content extraction."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def process_uploaded_file(
        self, 
        file_id: UUID, 
        submission_id: UUID,
        auto_populate: bool = True
    ) -> AIProcessingResponse:
        """Process an uploaded file and extract content for dossier sections."""
        
        start_time = time.time()
        
        # Log the start of file processing
        AILogger.log_simple_call(
            function_name="process_uploaded_file",
            model="orchestration",
            duration=0,
            success=True,
            additional_data={
                "file_id": str(file_id),
                "submission_id": str(submission_id),
                "auto_populate": auto_populate,
                "status": "STARTED"
            }
        )
        
        try:
            # Get file record
            file_record = self.db.query(UploadedFile).filter(
                UploadedFile.id == file_id
            ).first()
            
            if not file_record:
                raise ValueError(f"File not found: {file_id}")
            
            # Get dossier sections for the submission — leaves only (parents are folders)
            parent_id_subq = self.db.query(DossierSection.parent_section_id).filter(
                DossierSection.submission_id == submission_id,
                DossierSection.parent_section_id.isnot(None),
            ).subquery()
            dossier_sections = self.db.query(DossierSection).filter(
                DossierSection.submission_id == submission_id,
                ~DossierSection.id.in_(parent_id_subq),
            ).all()

            if not dossier_sections:
                raise ValueError(f"No leaf dossier sections found for submission: {submission_id}")
            
            # Parse document
            file_path = file_record.file_path
            if not Path(file_path).exists():
                raise ValueError(f"File not found on disk: {file_path}")
            
            document_content = document_parser.parse_document(file_path, file_record.mime_type)
            
            # Map content to sections using AI or fallback to keyword matching
            section_mappings = []
            
            if sarvam_ai_service:
                # Use Sarvam AI for intelligent content extraction
                print("Using Sarvam AI for content extraction...")
                for section in dossier_sections:
                    try:
                        # Get requirements for this section (prefer template requirements over generic ones)
                        requirements = (section.content_requirements or 
                                      content_mapper.get_section_requirements(section.section_code))
                        
                        # Extract content using Sarvam AI
                        ai_mapping = sarvam_ai_service.extract_section_content(
                            document_content.text, 
                            section, 
                            requirements
                        )
                        
                        if ai_mapping:
                            section_mappings.append(ai_mapping)
                            print(f"✅ AI extracted content for {section.section_code} (confidence: {ai_mapping.confidence_score:.2f})")
                        else:
                            print(f"⚠️ No AI content extracted for {section.section_code}")
                            
                    except Exception as e:
                        print(f"❌ AI extraction failed for {section.section_code}: {e}")
                        # Fallback to keyword matching for this section
                        keyword_mappings = content_mapper.map_content_to_sections(
                            document_content, [section]
                        )
                        section_mappings.extend(keyword_mappings)
            else:
                # Fallback to keyword matching if Sarvam AI not available
                print("Using keyword matching (Sarvam AI not configured)...")
                section_mappings = content_mapper.map_content_to_sections(
                    document_content, dossier_sections
                )
            
            # Update sections if auto_populate is enabled
            updated_sections = []
            if auto_populate:
                updated_sections = self._update_sections_with_ai_content(section_mappings, file_id)
            
            # Create extraction result
            extraction_result = AIExtractionResult(
                document_content=document_content,
                section_mappings=section_mappings,
                processing_time=time.time() - start_time,
                success=True
            )
            
            # Log successful completion
            duration = time.time() - start_time
            AILogger.log_simple_call(
                function_name="process_uploaded_file",
                model="orchestration",
                duration=duration,
                success=True,
                additional_data={
                    "file_id": str(file_id),
                    "submission_id": str(submission_id),
                    "sections_mapped": len(section_mappings),
                    "sections_updated": len(updated_sections),
                    "file_type": file_record.file_type.value if hasattr(file_record, 'file_type') else "unknown",
                    "status": "COMPLETED"
                }
            )
            
            return AIProcessingResponse(
                file_id=file_id,
                submission_id=submission_id,
                extraction_result=extraction_result,
                sections_updated=updated_sections,
                message=f"Successfully processed file and mapped content to {len(section_mappings)} sections"
            )
            
        except Exception as e:
            # Log error
            duration = time.time() - start_time
            AILogger.log_simple_call(
                function_name="process_uploaded_file",
                model="orchestration",
                duration=duration,
                success=False,
                error_message=str(e),
                additional_data={
                    "file_id": str(file_id),
                    "submission_id": str(submission_id),
                    "status": "ERROR"
                }
            )
            
            # Return error response
            extraction_result = AIExtractionResult(
                document_content=DocumentContent(
                    text="",
                    file_type="unknown",
                    extraction_method="error"
                ),
                section_mappings=[],
                processing_time=duration,
                success=False,
                error_message=str(e)
            )
            
            return AIProcessingResponse(
                file_id=file_id,
                submission_id=submission_id,
                extraction_result=extraction_result,
                sections_updated=[],
                message=f"Failed to process file: {str(e)}"
            )
    
    def _update_sections_with_ai_content(self, mappings: List[SectionMapping], source_file_id: UUID = None) -> List[UUID]:
        """Update dossier sections with AI-extracted content, handling conflicts intelligently."""
        
        updated_sections = []
        
        for mapping in mappings:
            # Only update if confidence is high enough
            if mapping.confidence_score < 0.3:
                continue
            
            section = self.db.query(DossierSection).filter(
                DossierSection.id == mapping.section_id
            ).first()
            
            if section:
                # Check for conflicts with existing AI content
                conflict_detected = False
                existing_content = section.ai_extracted_content
                new_content = mapping.extracted_content
                
                if (existing_content and existing_content.strip() != "" and 
                    existing_content != new_content):
                    
                    conflict_detected = True
                    print(f"🔥 CONFLICT detected in section {section.section_code}:")
                    print(f"   Existing: {existing_content[:100]}...")
                    print(f"   New:      {new_content[:100]}...")
                    print(f"   Confidence: {section.ai_confidence_score:.2f} vs {mapping.confidence_score:.2f}")
                
                # Handle conflicts with comprehensive tracking
                if conflict_detected:
                    # Initialize conflict sources if not exists
                    if not section.conflict_sources:
                        section.conflict_sources = []
                    
                    # Add new conflicting source
                    conflict_entry = {
                        "file_id": str(source_file_id) if source_file_id else "unknown",
                        "content": new_content,
                        "confidence": mapping.confidence_score,
                        "timestamp": time.time()
                    }
                    
                    # Avoid duplicate entries
                    existing_conflicts = section.conflict_sources or []
                    if not any(c.get("content") == new_content for c in existing_conflicts):
                        existing_conflicts.append(conflict_entry)
                        section.conflict_sources = existing_conflicts
                        section.has_conflicts = True
                    
                    # Resolution strategy: Use highest confidence content
                    if mapping.confidence_score > (section.ai_confidence_score or 0):
                        print(f"   → Using NEW content (higher confidence: {mapping.confidence_score:.2f})")
                        section.ai_extracted_content = new_content
                        section.ai_confidence_score = mapping.confidence_score
                        section.source_file_id = source_file_id
                        
                        # Don't auto-update main content - let user decide
                        # Only update if content was previously auto-generated from AI
                        if (not section.content or section.content.strip() == "" or 
                            section.content == section.ai_extracted_content):
                            # Content is empty or was AI-generated, so we can update it
                            pass  # Don't auto-update, let user choose
                    else:
                        print(f"   → Keeping EXISTING content (higher confidence: {section.ai_confidence_score:.2f})")
                        # Still track the conflict but don't change primary content
                
                else:
                    # No conflict, normal update
                    section.ai_extracted_content = new_content
                    section.ai_confidence_score = mapping.confidence_score
                    section.source_file_id = source_file_id
                    section.has_conflicts = False
                    section.conflict_sources = None
                    
                    # Don't auto-populate content - let user decide whether to use AI content
                    # This keeps ai_extracted_content separate from user content
                    section.completion_percentage = min(int(mapping.confidence_score * 100), 40)  # Lower % since it's just AI suggestion
                
                updated_sections.append(section.id)
        
        # Commit changes
        if updated_sections:
            self.db.commit()
        
        return updated_sections
    
    def get_content_suggestions(self, section_id: UUID) -> List[ContentSuggestion]:
        """Get AI content suggestions for a specific dossier section."""
        
        section = self.db.query(DossierSection).filter(
            DossierSection.id == section_id
        ).first()
        
        if not section:
            return []
        
        suggestions = []
        
        # Get requirements for this section
        # Use actual template requirements if available, fallback to generic ones
        requirements = (section.content_requirements or 
                       content_mapper.get_section_requirements(section.section_code))
        
        # If section has AI extracted content, create suggestion
        if section.ai_extracted_content and section.ai_confidence_score:
            suggestion = ContentSuggestion(
                section_id=section_id,
                suggested_content=section.ai_extracted_content,
                confidence_score=section.ai_confidence_score,
                source_files=["AI extracted content"],
                reasoning=f"Content extracted from uploaded documents with {section.ai_confidence_score:.0%} confidence"
            )
            suggestions.append(suggestion)
        
        # Generate placeholder suggestion based on requirements
        if requirements:
            placeholder_content = self._generate_placeholder_content(section, requirements)
            placeholder_suggestion = ContentSuggestion(
                section_id=section_id,
                suggested_content=placeholder_content,
                confidence_score=0.5,  # Medium confidence for template content
                source_files=["IMDRF template"],
                reasoning="Template-based content structure based on IMDRF requirements"
            )
            suggestions.append(placeholder_suggestion)
        
        return suggestions
    
    def _generate_placeholder_content(self, section: DossierSection, requirements: List[str]) -> str:
        """Generate placeholder content for a section based on requirements."""
        
        content_parts = [
            f"# {section.section_title}",
            "",
            f"## Section {section.section_code} - {section.section_title}",
            ""
        ]
        
        if section.section_description:
            content_parts.extend([
                "## Description",
                section.section_description,
                ""
            ])
        
        content_parts.extend([
            "## Required Information",
            ""
        ])
        
        for i, requirement in enumerate(requirements, 1):
            content_parts.append(f"{i}. **{requirement}**")
            content_parts.append(f"   [Please provide information about {requirement.lower()}]")
            content_parts.append("")
        
        content_parts.extend([
            "## Instructions",
            "- Replace the placeholder text above with actual content",
            "- Ensure all required information is provided",
            "- Review and validate before marking as complete",
            "",
            "---",
            "*This content was generated based on IMDRF template requirements.*"
        ])
        
        return "\n".join(content_parts)
    
    def analyze_submission_completeness(self, submission_id: UUID) -> Dict[str, Any]:
        """Analyze the completeness of a submission based on AI and manual content."""
        
        sections = self.db.query(DossierSection).filter(
            DossierSection.submission_id == submission_id
        ).all()
        
        if not sections:
            return {
                "total_sections": 0,
                "completed_sections": 0,
                "ai_assisted_sections": 0,
                "manual_sections": 0,
                "completion_percentage": 0,
                "missing_sections": []
            }
        
        completed_sections = 0
        ai_assisted_sections = 0
        manual_sections = 0
        missing_sections = []
        
        for section in sections:
            has_content = bool(section.content and section.content.strip())
            has_ai_content = bool(section.ai_extracted_content)
            
            if has_content:
                completed_sections += 1
                if has_ai_content:
                    ai_assisted_sections += 1
                else:
                    manual_sections += 1
            else:
                missing_sections.append({
                    "section_code": section.section_code,
                    "section_title": section.section_title,
                    "is_required": section.is_required,
                    "has_ai_content": has_ai_content
                })
        
        completion_percentage = (completed_sections / len(sections)) * 100 if sections else 0
        
        return {
            "total_sections": len(sections),
            "completed_sections": completed_sections,
            "ai_assisted_sections": ai_assisted_sections,
            "manual_sections": manual_sections,
            "completion_percentage": round(completion_percentage, 1),
            "missing_sections": missing_sections,
            "ai_coverage": round((ai_assisted_sections / len(sections)) * 100, 1) if sections else 0
        }
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get overall AI processing statistics."""
        
        # Count sections with AI content
        sections_with_ai = self.db.query(DossierSection).filter(
            DossierSection.ai_extracted_content.isnot(None)
        ).count()
        
        total_sections = self.db.query(DossierSection).count()
        
        # Average confidence score
        avg_confidence = self.db.query(
            DossierSection.ai_confidence_score
        ).filter(
            DossierSection.ai_confidence_score.isnot(None)
        ).all()
        
        avg_confidence_score = 0.0
        if avg_confidence:
            scores = [score[0] for score in avg_confidence if score[0] is not None]
            avg_confidence_score = sum(scores) / len(scores) if scores else 0.0
        
        return {
            "total_sections": total_sections,
            "ai_processed_sections": sections_with_ai,
            "ai_coverage_percentage": round((sections_with_ai / total_sections) * 100, 1) if total_sections else 0,
            "average_confidence_score": round(avg_confidence_score, 3),
            "processing_success_rate": 0.95  # Mock value - would track actual success rate
        }