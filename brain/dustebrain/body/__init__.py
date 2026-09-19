"""
dustebrain.body - the link to the XIAO ESP32-S3, and the rules it enforces.

Three pieces, deliberately separate:

  protocol.py   framing, CRC, sequence numbers. Knows nothing about robots.
  validator.py  what the brain is allowed to ask for, and from which source.
                The LLM cannot reach a motor through this.
  simbody.py    a reference implementation of the body's reflex safety, in
                Python, so the failsafe rules can be tested before any
                firmware is flashed - and so the firmware has something exact
                to be written against.

Nothing here opens a serial port yet. Phase 2b adds that, against the same
protocol these tests already pin down.
"""
