"""
Content mapping service for mapping extracted text to dossier sections using AI.
"""

import re
import json
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.ai.models import SectionMapping, DocumentContent
from app.dossier.models import DossierSection


class ContentMapper:
    """Service for mapping document content to dossier sections."""
    
    def __init__(self):
        # Keywords for mapping content to IMDRF sections
        self.section_keywords = {
            "1": {
                "keywords": ["administrative", "applicant", "company", "manufacturer", "contact", "organization", "regulatory"],
                "title": "Administrative Information"
            },
            "1.1": {
                "keywords": ["applicant", "company", "manufacturer", "contact", "address", "phone", "email", "organization"],
                "title": "Applicant Information"
            },
            "1.2": {
                "keywords": ["device", "name", "model", "identification", "product", "brand", "trademark", "nomenclature"],
                "title": "Device Identification"
            },
            "1.3": {
                "keywords": ["regulatory", "history", "approval", "clearance", "registration", "previous", "submission"],
                "title": "Regulatory History"
            },
            "2": {
                "keywords": ["description", "device", "technical", "specifications", "features", "characteristics"],
                "title": "Device Description"
            },
            "2.1": {
                "keywords": ["general", "description", "overview", "summary", "purpose", "function", "operation"],
                "title": "General Device Description"
            },
            "2.2": {
                "keywords": ["intended", "use", "purpose", "indication", "application", "clinical", "medical"],
                "title": "Intended Use"
            },
            "2.3": {
                "keywords": ["technical", "specifications", "parameters", "performance", "characteristics", "features"],
                "title": "Technical Specifications"
            },
            "3": {
                "keywords": ["quality", "management", "system", "qms", "iso", "13485", "procedures", "processes"],
                "title": "Quality Management System"
            },
            "3.1": {
                "keywords": ["quality", "system", "qms", "iso", "13485", "certification", "management"],
                "title": "Quality System Information"
            },
            "4": {
                "keywords": ["risk", "management", "analysis", "assessment", "hazard", "safety", "mitigation"],
                "title": "Risk Management"
            },
            "4.1": {
                "keywords": ["risk", "analysis", "assessment", "identification", "evaluation", "hazard"],
                "title": "Risk Analysis"
            },
            "5": {
                "keywords": ["clinical", "evidence", "data", "studies", "trials", "evaluation", "performance"],
                "title": "Clinical Evidence"
            },
            "5.1": {
                "keywords": ["clinical", "evaluation", "data", "studies", "evidence", "performance", "safety"],
                "title": "Clinical Evaluation"
            },
            "6": {
                "keywords": ["labeling", "label", "instructions", "use", "packaging", "symbols", "warnings"],
                "title": "Labeling"
            },
            "6.1": {
                "keywords": ["labeling", "label", "instructions", "user", "manual", "packaging"],
                "title": "Labeling Information"
            }
        }
    
    def map_content_to_sections(
        self, 
        document_content: DocumentContent, 
        dossier_sections: List[DossierSection]
    ) -> List[SectionMapping]:
        """Map document content to dossier sections using keyword matching."""
        
        mappings = []
        text = document_content.text.lower()
        
        # Create section lookup
        sections_by_code = {section.section_code: section for section in dossier_sections}
        
        for section in dossier_sections:
            section_code = section.section_code
            
            # Get keywords for this section
            keywords_info = self.section_keywords.get(section_code, {})
            keywords = keywords_info.get("keywords", [])
            
            if not keywords:
                continue
            
            # Find content related to this section
            section_content, confidence, matched_keywords = self._extract_section_content(
                text, keywords, section.section_title
            )
            
            if section_content and confidence > 0.1:  # Minimum confidence threshold
                mapping = SectionMapping(
                    section_id=section.id,
                    section_code=section.section_code,
                    section_title=section.section_title,
                    extracted_content=section_content,
                    confidence_score=confidence,
                    keywords_matched=matched_keywords
                )
                mappings.append(mapping)
        
        # Sort by confidence score (highest first)
        mappings.sort(key=lambda x: x.confidence_score, reverse=True)
        
        return mappings
    
    def _extract_section_content(
        self, 
        text: str, 
        keywords: List[str], 
        section_title: str
    ) -> tuple[str, float, List[str]]:
        """Extract content related to specific keywords and calculate confidence."""
        
        matched_keywords = []
        relevant_sentences = []
        
        # Split text into sentences
        sentences = self._split_into_sentences(text)
        
        for sentence in sentences:
            sentence_lower = sentence.lower()
            sentence_keywords = []
            
            # Check for keyword matches
            for keyword in keywords:
                if keyword.lower() in sentence_lower:
                    sentence_keywords.append(keyword)
                    if keyword not in matched_keywords:
                        matched_keywords.append(keyword)
            
            # If sentence contains keywords, include it and surrounding context
            if sentence_keywords:
                relevant_sentences.append(sentence.strip())
        
        # Calculate confidence based on keyword matches and content length
        if not matched_keywords:
            return "", 0.0, []
        
        # Confidence factors
        keyword_coverage = len(matched_keywords) / len(keywords)  # 0-1
        content_length_factor = min(len(relevant_sentences) / 3, 1.0)  # 0-1, optimal around 3 sentences
        
        # Boost confidence if section title keywords are found
        title_boost = 0.0
        title_words = section_title.lower().split()
        for word in title_words:
            if word in text and len(word) > 3:  # Ignore short words
                title_boost += 0.1
        
        confidence = (keyword_coverage * 0.6 + content_length_factor * 0.3 + min(title_boost, 0.1))
        confidence = min(confidence, 1.0)
        
        # Join relevant sentences
        content = "\n".join(relevant_sentences[:10])  # Limit to 10 sentences max
        
        return content, confidence, matched_keywords
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences using simple regex."""
        # Simple sentence splitting - can be improved with NLTK if needed
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]
    
    def suggest_content_for_section(
        self, 
        section: DossierSection, 
        available_content: List[str]
    ) -> Optional[str]:
        """Suggest content for a specific section based on available extracted content."""
        
        section_code = section.section_code
        keywords_info = self.section_keywords.get(section_code, {})
        keywords = keywords_info.get("keywords", [])
        
        if not keywords:
            return None
        
        # Find best matching content
        best_content = ""
        best_score = 0.0
        
        for content in available_content:
            content_lower = content.lower()
            
            # Count keyword matches
            matches = sum(1 for keyword in keywords if keyword in content_lower)
            score = matches / len(keywords) if keywords else 0
            
            if score > best_score and score > 0.2:  # Minimum threshold
                best_score = score
                best_content = content
        
        return best_content if best_content else None
    
    def get_section_requirements(self, section_code: str) -> List[str]:
        """Get content requirements for a specific section."""
        # This would ideally come from the IMDRF template
        # For now, return generic requirements based on section
        
        requirements_map = {
            "1.1": [
                "Company name and full address",
                "Contact person details (name, phone, email)",
                "Business registration information",
                "Regulatory contact information"
            ],
            "1.2": [
                "Device name and model number",
                "Device classification",
                "Intended use statement",
                "Regulatory product code"
            ],
            "2.1": [
                "Comprehensive device description",
                "Device components and accessories",
                "Operating principles",
                "Key features and benefits"
            ],
            "2.2": [
                "Intended use statement",
                "Target patient population",
                "Clinical indications",
                "Contraindications"
            ],
            "3.1": [
                "ISO 13485 certification details",
                "Quality management system documentation",
                "Manufacturing site information",
                "Quality control procedures"
            ],
            "4.1": [
                "Risk analysis methodology",
                "Identified hazards and risks",
                "Risk control measures",
                "Residual risk assessment"
            ],
            "5.1": [
                "Clinical evaluation plan",
                "Clinical data summary",
                "Literature review",
                "Post-market clinical follow-up"
            ]
        }
        
        return requirements_map.get(section_code, [
            "Provide relevant documentation",
            "Include supporting evidence",
            "Ensure regulatory compliance"
        ])


# Global content mapper instance
content_mapper = ContentMapper()