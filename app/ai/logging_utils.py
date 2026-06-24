"""
AI API logging utilities for comprehensive request/response tracking.
"""

import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from app.core.config import settings

# Configure logger for AI API calls
logger = logging.getLogger("ai_api")
logger.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create file handler if not exists
if not logger.handlers:
    import os
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..')
    os.makedirs(log_dir, exist_ok=True)
    
    # Create file handler
    log_file = os.path.join(log_dir, 'logs.txt')
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Prevent propagation to root logger to avoid console output
    logger.propagate = False


@dataclass
class AIRequestLog:
    """Data structure for AI API request logging."""
    function_name: str
    model: str
    start_time: float
    request_data: Dict[str, Any]
    request_size_chars: int
    
    
@dataclass
class AIResponseLog:
    """Data structure for AI API response logging."""
    success: bool
    duration_seconds: float
    response_data: Optional[str] = None
    response_length: int = 0
    tokens_used: Optional[int] = None
    error_message: Optional[str] = None
    

class AILogger:
    """Comprehensive AI API request/response logger."""

    SENSITIVE_KEYS = {
        "authorization",
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
    }
    
    @staticmethod
    def sanitize_content(content: str, max_chars: int = None) -> str:
        """Truncate content before logging to reduce data exposure."""
        if not content:
            return ""

        effective_max_chars = max_chars or settings.AI_LOG_MAX_CONTENT_CHARS
        if len(content) <= effective_max_chars:
            return content

        return f"{content[:effective_max_chars]}... [truncated {len(content) - effective_max_chars} chars]"
    
    @staticmethod
    def sanitize_request_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize request data for logging."""
        sanitized = {}
        
        for key, value in data.items():
            if key.lower() in AILogger.SENSITIVE_KEYS:
                sanitized[key] = "[REDACTED]"
                continue

            if key == "messages" and isinstance(value, list):
                sanitized[key] = []
                for msg in value:
                    if isinstance(msg, dict) and "content" in msg:
                        sanitized_msg = msg.copy()
                        sanitized_msg["content"] = AILogger.sanitize_content(msg["content"])
                        sanitized[key].append(sanitized_msg)
                    else:
                        sanitized[key].append(msg)
            elif isinstance(value, str):
                sanitized[key] = AILogger.sanitize_content(value)
            else:
                sanitized[key] = value
                
        return sanitized
    
    @staticmethod
    def start_request(
        function_name: str,
        model: str,
        request_data: Dict[str, Any]
    ) -> AIRequestLog:
        """Log the start of an AI API request."""
        
        # Calculate request size
        request_str = json.dumps(request_data, default=str)
        request_size = len(request_str)
        
        # Create request log
        request_log = AIRequestLog(
            function_name=function_name,
            model=model,
            start_time=time.time(),
            request_data=request_data,
            request_size_chars=request_size
        )
        
        # Log request start
        message = (
            f"AI API Call [STARTED] | Function: {function_name} | "
            f"Model: {model} | Request Size: {request_size} chars"
        )
        if settings.AI_LOG_INCLUDE_CONTENT:
            sanitized_data = AILogger.sanitize_request_data(request_data)
            message += f" | Request: {json.dumps(sanitized_data, default=str)}"
        logger.info(message)
        
        return request_log
    
    @staticmethod
    def end_request(
        request_log: AIRequestLog,
        response_log: AIResponseLog
    ):
        """Log the completion of an AI API request."""
        
        # Calculate metrics
        duration_ms = response_log.duration_seconds * 1000
        tokens_per_second = (
            response_log.tokens_used / response_log.duration_seconds 
            if response_log.tokens_used and response_log.duration_seconds > 0 
            else 0
        )
        
        # Prepare log data
        log_data = {
            "function": request_log.function_name,
            "model": request_log.model,
            "duration_seconds": round(response_log.duration_seconds, 3),
            "duration_ms": round(duration_ms, 1),
            "success": response_log.success,
            "timestamp": datetime.fromtimestamp(request_log.start_time).isoformat(),
            "request_size_chars": request_log.request_size_chars,
            "response_length": response_log.response_length
        }
        
        if response_log.tokens_used:
            log_data["tokens_used"] = response_log.tokens_used
            log_data["tokens_per_second"] = round(tokens_per_second, 2)
        
        # Status and main message
        status = "SUCCESS" if response_log.success else "ERROR"
        main_message = (
            f"AI API Call [{status}] | Function: {request_log.function_name} | "
            f"Model: {request_log.model} | Duration: {response_log.duration_seconds:.3f}s"
        )
        
        if response_log.tokens_used:
            main_message += f" | Tokens: {response_log.tokens_used} | Rate: {tokens_per_second:.2f}/s"
        
        main_message += f" | Data: {json.dumps(log_data, default=str)}"
        
        if settings.AI_LOG_INCLUDE_CONTENT:
            # Add sanitized request data for debugging
            sanitized_request = AILogger.sanitize_request_data(request_log.request_data)
            main_message += f" | Request: {json.dumps(sanitized_request, default=str)}"

            # Add response content only when explicitly enabled
            if response_log.response_data:
                sanitized_response = AILogger.sanitize_content(response_log.response_data)
                main_message += f" | Response: {sanitized_response}"
        
        # Add error message if failed
        if not response_log.success and response_log.error_message:
            main_message += f" | Error: {response_log.error_message}"
        
        # Log based on success/failure
        if response_log.success:
            logger.info(main_message)
        else:
            logger.error(main_message)
    
    @staticmethod
    def log_simple_call(
        function_name: str,
        model: str,
        duration: float,
        success: bool,
        error_message: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log a simple AI call without detailed request/response tracking."""
        
        status = "SUCCESS" if success else "ERROR"
        log_data = {
            "function": function_name,
            "model": model,
            "duration_seconds": round(duration, 3),
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
        
        if additional_data:
            log_data.update(additional_data)
        
        message = (
            f"AI API Call [{status}] | Function: {function_name} | "
            f"Model: {model} | Duration: {duration:.3f}s | "
            f"Data: {json.dumps(log_data, default=str)}"
        )
        
        if error_message:
            message += f" | Error: {error_message}"
        
        if success:
            logger.info(message)
        else:
            logger.error(message)
from dataclasses import dataclass

# Configure logger for AI API calls
logger = logging.getLogger("ai_api")
logger.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create file handler if not exists
if not logger.handlers:
    import os
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..')
    os.makedirs(log_dir, exist_ok=True)
    
    # Create file handler
    log_file = os.path.join(log_dir, 'logs.txt')
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Prevent propagation to root logger to avoid console output
    logger.propagate = False


@dataclass
class AIRequestLog:
    """Data structure for AI API request logging."""
    function_name: str
    model: str
    start_time: float
    request_data: Dict[str, Any]
    request_size_chars: int
    
    
@dataclass
class AIResponseLog:
    """Data structure for AI API response logging."""
    success: bool
    duration_seconds: float
    response_data: Optional[str] = None
    response_length: int = 0
    tokens_used: Optional[int] = None
    error_message: Optional[str] = None
    

class AILogger:
    """Comprehensive AI API request/response logger."""
    
    @staticmethod
    def sanitize_content(content: str, max_chars: int = 500) -> str:
        """Sanitize and truncate content for logging."""
        if not content:
            return ""
        
        # If content is very long (likely file content), show beginning + placeholder
        if len(content) > 10000:
            return f"{content[:100]}... #file_content_truncated# ...{content[-50:]}"
        
        # Truncate if still too long
        if len(content) > max_chars:
            return content[:max_chars] + "..."
        
        return content
    
    @staticmethod
    def sanitize_request_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize request data for logging."""
        sanitized = {}
        
        for key, value in data.items():
            if key == "messages" and isinstance(value, list):
                sanitized[key] = []
                for msg in value:
                    if isinstance(msg, dict) and "content" in msg:
                        sanitized_msg = msg.copy()
                        sanitized_msg["content"] = AILogger.sanitize_content(msg["content"])
                        sanitized[key].append(sanitized_msg)
                    else:
                        sanitized[key].append(msg)
            elif isinstance(value, str):
                sanitized[key] = AILogger.sanitize_content(value)
            else:
                sanitized[key] = value
                
        return sanitized
    
    @staticmethod
    def start_request(
        function_name: str,
        model: str,
        request_data: Dict[str, Any]
    ) -> AIRequestLog:
        """Log the start of an AI API request."""
        
        # Calculate request size
        request_str = json.dumps(request_data, default=str)
        request_size = len(request_str)
        
        # Create request log
        request_log = AIRequestLog(
            function_name=function_name,
            model=model,
            start_time=time.time(),
            request_data=request_data,
            request_size_chars=request_size
        )
        
        # Log request start
        sanitized_data = AILogger.sanitize_request_data(request_data)
        logger.info(
            f"AI API Call [STARTED] | Function: {function_name} | "
            f"Model: {model} | Request Size: {request_size} chars | "
            f"Request: {json.dumps(sanitized_data, default=str)}"
        )
        
        return request_log
    
    @staticmethod
    def end_request(
        request_log: AIRequestLog,
        response_log: AIResponseLog
    ):
        """Log the completion of an AI API request."""
        
        # Calculate metrics
        duration_ms = response_log.duration_seconds * 1000
        tokens_per_second = (
            response_log.tokens_used / response_log.duration_seconds 
            if response_log.tokens_used and response_log.duration_seconds > 0 
            else 0
        )
        
        # Prepare log data
        log_data = {
            "function": request_log.function_name,
            "model": request_log.model,
            "duration_seconds": round(response_log.duration_seconds, 3),
            "duration_ms": round(duration_ms, 1),
            "success": response_log.success,
            "timestamp": datetime.fromtimestamp(request_log.start_time).isoformat(),
            "request_size_chars": request_log.request_size_chars,
            "response_length": response_log.response_length
        }
        
        if response_log.tokens_used:
            log_data["tokens_used"] = response_log.tokens_used
            log_data["tokens_per_second"] = round(tokens_per_second, 2)
        
        # Status and main message
        status = "SUCCESS" if response_log.success else "ERROR"
        main_message = (
            f"AI API Call [{status}] | Function: {request_log.function_name} | "
            f"Model: {request_log.model} | Duration: {response_log.duration_seconds:.3f}s"
        )
        
        if response_log.tokens_used:
            main_message += f" | Tokens: {response_log.tokens_used} | Rate: {tokens_per_second:.2f}/s"
        
        main_message += f" | Data: {json.dumps(log_data, default=str)}"
        
        # Add sanitized request data for debugging
        sanitized_request = AILogger.sanitize_request_data(request_log.request_data)
        main_message += f" | Request: {json.dumps(sanitized_request, default=str)}"
        
        # Add response content if available and not too long
        if response_log.response_data:
            sanitized_response = AILogger.sanitize_content(response_log.response_data, 500)
            main_message += f" | Response: {sanitized_response}"
        
        # Add error message if failed
        if not response_log.success and response_log.error_message:
            main_message += f" | Error: {response_log.error_message}"
        
        # Log based on success/failure
        if response_log.success:
            logger.info(main_message)
        else:
            logger.error(main_message)
    
    @staticmethod
    def log_simple_call(
        function_name: str,
        model: str,
        duration: float,
        success: bool,
        error_message: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log a simple AI call without detailed request/response tracking."""
        
        status = "SUCCESS" if success else "ERROR"
        log_data = {
            "function": function_name,
            "model": model,
            "duration_seconds": round(duration, 3),
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
        
        if additional_data:
            log_data.update(additional_data)
        
        message = (
            f"AI API Call [{status}] | Function: {function_name} | "
            f"Model: {model} | Duration: {duration:.3f}s | "
            f"Data: {json.dumps(log_data, default=str)}"
        )
        
        if error_message:
            message += f" | Error: {error_message}"
        
        if success:
            logger.info(message)
        else:
            logger.error(message)