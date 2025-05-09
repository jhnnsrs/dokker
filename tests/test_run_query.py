import requests
from dokker import local, HealthCheck, Deployment
import pytest


def test_check_port_inspectable(composed_project: Deployment):
    
    
    
    base_adress = composed_project.spec.services["mikro"].get_port_for_internal(80)
    
    assert base_adress.published == 6888, f"Expected 6888, got {base_adress}"
    
    
    
    
def test_check_watcher(composed_project: Deployment):
    """Test the watcher"""
    
    base_adress = composed_project.spec.services["mikro"].get_port_for_internal(80)
    
    watcher = composed_project.create_watcher(
        "mikro"
    )
    
    
    try:
        with watcher:
            
            requests.get(f"http://localhost:{base_adress.published}/show_return_an_aeeor")
            
    except Exception as e:
        print(f"Request failed: {e}")
        
        
    assert watcher.collected_logs, "No logs collected"
        