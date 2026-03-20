"""
trellis.senses.file_watcher — Watched Folder Intake

Monitors a directory for new files (voice note transcripts, dropped links,
screenshots, etc.) and creates events for the main loop to process.

Watch target: {vault_path}/_ivy/inbox/
"""

# TODO: Phase 1 implementation
# - Use watchdog library for filesystem events
# - Detect new files in _ivy/inbox/ subdirectories
# - Create intake events for the main loop
# - Move processed files to appropriate vault locations
