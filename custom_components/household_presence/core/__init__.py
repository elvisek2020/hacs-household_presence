"""Pure presence engine without Home Assistant imports (NFR-04).

Everything time related comes in through ``Snapshot.now`` so the engine can be
driven by tests without a running Home Assistant.
"""
