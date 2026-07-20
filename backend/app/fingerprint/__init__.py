"""Technology Fingerprint Engine.

Pure, deterministic detection of a website's technology stack from live signals
(HTTP headers + HTML + well-known paths). No credentials required. The detector
here does no I/O; the service layer fetches and feeds it inputs so it stays
unit-testable.
"""
