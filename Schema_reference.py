
EXPECTED_SCHEMA = {
    "metadata": {
        "filename": str,
        "total_pages": int,
        "extraction_timestamp": str,
        "extractor_version": str,
    },
    "sections": [
        {
            "section_id": str,       
            "title": str,
            "page_start": int,
            "page_end": int,
            "text": str,
        }
    ],
    "tables": [
        {
            "table_id": str,         
            "page": int,
            "caption": str,
            "headers": list,
            "rows": list,            
            "section_ref": str,      
        }
    ],
    "figures": [
        {
            "figure_id": str,        
            "page": int,
            "caption": str,
            "semantic_insight": str, 
            "section_ref": str,
        }
    ],
    "numbers": [
        {
            "number_id": str,        
            "value": float,
            "unit": str,
            "context": str,          
            "page": int,
            "section_ref": str,
        }
    ],
}

SEVERITY = {
    "CRITICAL": "DANGER",   
    "WARNING":  "WARNING",   
    "INFO":     "INFO",   
    "PASS":     "PASSED",   
}