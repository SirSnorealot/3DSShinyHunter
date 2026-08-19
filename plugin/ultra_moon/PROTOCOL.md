# Plugin protocol v1

Transport: UDP, default port 4951. All integer fields are little-endian.

Request (20 bytes):

- magic: 4 bytes, `SH3D`
- version: u8 = 1
- command: u8 (`1=PING`, `2=READ`)
- flags: u16
- request_id: u32
- address: u32
- size: u32

Response header (16 bytes), followed by payload:

- magic: 4 bytes, `SH3D`
- version: u8 = 1
- status: u8 (`0=OK`, `1=BAD_REQUEST`, `2=UNSUPPORTED`, `3=DENIED`)
- reserved: u16
- request_id: u32
- payload_size: u32

The Ultra Moon proof-of-concept only permits PK7-core reads from explicitly allow-listed addresses.
