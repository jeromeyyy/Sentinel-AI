#!/usr/bin/env python3
"""
Test RTSP normalization & typo correction logic (self-contained, no imports).
Validates that rstp:// typos are corrected and stream sources are normalized.
"""

def _normalize_stream_source(video_path):
    """Normalize stream source paths and fix typos."""
    if video_path is None:
        return None

    raw = str(video_path).strip()
    if not raw:
        return None

    # Fix rstp:// typo → rtsp://
    if raw.lower().startswith("rstp://"):
        return f"rtsp://{raw[7:]}"

    return raw


# Test cases: (input, expected_output)
test_cases = [
    ('rstp://demo.example.com/live', 'rtsp://demo.example.com/live'),
    ('RSTP://demo.example.com/live', 'rtsp://demo.example.com/live'),
    ('rtsp://demo.example.com/live', 'rtsp://demo.example.com/live'),
    ('RTSP://demo.example.com/live', 'RTSP://demo.example.com/live'),
    ('http://demo.example.com/stream.m3u8', 'http://demo.example.com/stream.m3u8'),
    ('https://demo.example.com/stream.m3u8', 'https://demo.example.com/stream.m3u8'),
    ('  rstp://example.com/live  ', 'rtsp://example.com/live'),
    ('  RSTP://EXAMPLE.COM/LIVE  ', 'rtsp://EXAMPLE.COM/LIVE'),
    (None, None),
    ('', None),
    ('   ', None),
    ('myfile.mp4', 'myfile.mp4'),
    ('/path/to/video.mp4', '/path/to/video.mp4'),
    ('C:\\videos\\camera.mp4', 'C:\\videos\\camera.mp4'),
]

print("=" * 80)
print("RTSP NORMALIZATION & TYPO CORRECTION TEST".center(80))
print("=" * 80)
print()

all_pass = True
for input_val, expected in test_cases:
    result = _normalize_stream_source(input_val)
    status = "✓ PASS" if result == expected else "✗ FAIL"
    if result != expected:
        all_pass = False
        print(f"{status} <-- MISMATCH")
    else:
        print(f"{status}")
    print(f"  Input:    {repr(input_val)}")
    print(f"  Expected: {repr(expected)}")
    print(f"  Got:      {repr(result)}")
    print()

print("=" * 80)
if all_pass:
    print("✓ ALL TESTS PASSED".center(80))
    print()
    print("RTSP Stream Fix Summary:".ljust(80))
    print("  ✓ rstp:// typos are corrected to rtsp://")
    print("  ✓ Local video paths and HTTP/HTTPS URLs are preserved")
    print("  ✓ Leading/trailing whitespace is trimmed")
    print("  ✓ Empty/None values are handled safely")
    print()
    print("Next: Restart backend service and test RTSP stream input UI".ljust(80))
else:
    print("✗ SOME TESTS FAILED - REVIEW OUTPUT ABOVE".center(80))
    import sys
    sys.exit(1)

print("=" * 80)
