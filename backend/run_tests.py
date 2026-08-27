"""
SentinelAI Backend Test Runner
Runs automated tests across Authentication, API Endpoints, Data Isolation, and Vision & Behavior Pipelines.
"""
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_auth
import test_api
import test_data_isolation
import test_vision_pipeline
from fastapi.testclient import TestClient
from main import app

def run_suite():
    passed = 0
    failed = 0
    client = TestClient(app)

    print("=" * 60)
    print("🚀 RUNNING SENTINEL AI AUTOMATED TEST SUITE")
    print("=" * 60)

    # 1. Auth unit tests
    auth_tests = [
        ("test_user_model_creation", lambda: test_auth.test_user_model_creation()),
        ("test_jwt_token_generation_and_validation", lambda: test_auth.test_jwt_token_generation_and_validation()),
        ("test_expired_jwt_token", lambda: test_auth.test_expired_jwt_token()),
        ("test_oauth_state_generation_and_validation", lambda: test_auth.test_oauth_state_generation_and_validation()),
        ("test_google_auth_url_structure", lambda: test_auth.test_google_auth_url_structure()),
    ]

    print("\n📦 Running Authentication Tests:")
    for name, test_func in auth_tests:
        try:
            test_func()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1

    # 2. API endpoint integration tests
    auth_headers = test_api.get_auth_headers()
    api_tests = [
        ("test_health_endpoint", lambda: test_api.test_health_endpoint(client)),
        ("test_zones_endpoint", lambda: test_api.test_zones_endpoint(client)),
        ("test_modules_endpoint", lambda: test_api.test_modules_endpoint(client)),
        ("test_auth_verify_unauthenticated", lambda: test_api.test_auth_verify_unauthenticated(client)),
        ("test_auth_verify_authenticated", lambda: test_api.test_auth_verify_authenticated(client, auth_headers)),
        ("test_auth_me_endpoint", lambda: test_api.test_auth_me_endpoint(client, auth_headers)),
        ("test_stats_endpoint", lambda: test_api.test_stats_endpoint(client, auth_headers)),
    ]

    print("\n🌐 Running API Endpoint Tests:")
    for name, test_func in api_tests:
        try:
            test_func()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1

    # 3. Data isolation tests
    isolation_tests = [
        ("test_tenant_data_isolation", lambda: test_data_isolation.test_tenant_data_isolation(client)),
    ]

    print("\n🔒 Running Multi-Tenant Data Isolation Tests:")
    for name, test_func in isolation_tests:
        try:
            test_func()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1

    # 4. Computer Vision & Behavior Pipeline tests
    vision_tests = [
        ("test_environment_registry_configs", lambda: test_vision_pipeline.test_environment_registry_configs()),
        ("test_phone_use_spatial_temporal_detection", lambda: test_vision_pipeline.test_phone_use_spatial_temporal_detection()),
        ("test_fight_altercation_detection", lambda: test_vision_pipeline.test_fight_altercation_detection()),
        ("test_fire_smoke_temporal_tracker", lambda: test_vision_pipeline.test_fire_smoke_temporal_tracker()),
        ("test_crowd_density_detector", lambda: test_vision_pipeline.test_crowd_density_detector()),
        ("test_loitering_dwell_detector", lambda: test_vision_pipeline.test_loitering_dwell_detector()),
        ("test_restricted_zone_geofencing", lambda: test_vision_pipeline.test_restricted_zone_geofencing()),
        ("test_after_hours_schedule_monitor", lambda: test_vision_pipeline.test_after_hours_schedule_monitor()),
        ("test_global_person_tracking_and_topology", lambda: test_vision_pipeline.test_global_person_tracking_and_topology()),
        ("test_incident_engine_deduplication", lambda: test_vision_pipeline.test_incident_engine_deduplication()),
    ]

    print("\n👁️  Running Computer Vision & Behavior Pipeline Tests:")
    for name, test_func in vision_tests:
        try:
            test_func()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"🎯 TEST RESULTS: {passed} PASSED, {failed} FAILED")
    print("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run_suite())
