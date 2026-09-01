Taken from https://www.reddit.com/r/Elektron/comments/1w3i7ar/comment/p70lgm0/

Elektron Digitone II (.dn2prj) & Digitakt II (.dt2prj)

---

## 1. Container & Streaming Envelope (Shared Architecture)

```
+-----------------------------------------------------------------------------+
| 1. ZIP Archive Envelope (.dn2prj / .dt2prj)                                 |
|    |-- manifest.json  {"ProductType": ["43" | "37"], "Payload": "Project"}  |
|    -- Payload        Binary container stream                                |
+-----------------------------------------------------------------------------+
| 2. Payload Binary Stream Layout                                             |
|    |-- 31-byte Container Header (Magic: 0xAC 11 D3 03, byte 29 = 0x01/0x00) |
|    |-- Continuous 32KB Chunked LZ4 Block Stream (64KB sliding history)      |
|    |-- 4-byte Stream Null Terminator (0x00 00 00 00)                        |
|    -- 12-byte Footer [CRC-32 (4B BE)] [Stream Len (4B BE)] [AA A1 DA AA]    |
+-----------------------------------------------------------------------------+
| 3. Decompressed Monolithic RAM Image (Fixed Memory Layout)                  |
|    |-- Start Magic: 0xBEEFBACE (Offset 0x000000)                            |
|    |-- Project Header, Patterns, Kits, Sound Pool, Globals, Song Mode       |
|    -- End Magic:   0xBACEF00C (Exact last 4 bytes)                          |
+-----------------------------------------------------------------------------+
```

- Header Size: 31 bytes (0x1F)
  - 0x00..0x03: Magic 0xAC 11 D3 03
  - 0x1D (Byte 29): 0x01 (Compressed LZ4 payload) or 0x00 (Raw uncompressed image)
- Compression Engine: Continuous 32,768-byte blocks with a 65,536-byte sliding history dictionary (FUN_401321f0)
- Footer Size: 12 bytes (0x0C) (FUN_400e96e0)
  - 0x00..0x03: IEEE 802.3 CRC-32 (computed over compressed stream with seed 0xFFFFFFFF)
  - 0x04..0x07: Total compressed stream length (Big-Endian uint32)
  - 0x08..0x0B: Footer Magic 0xAA A1 DA AA

---

## 2. Monolithic RAM Image Partition Matrices

| Memory Partition         | Digitone II (.dn2prj)                 | Digitakt II (.dt2prj)                 |
| ------------------------ | ------------------------------------- | ------------------------------------- |
| Product Type ID          | "43"                                  | "37"                                  |
| Format Version           | Format 3                              | Format 4                              |
| Total Image Size         | 12,889,604 bytes (0xC4AE04)           | 14,521,348 bytes (0xDD9404)           |
| Start Magic              | 0x00000000 (0xBEEFBACE)               | 0x00000000 (0xBEEFBACE)               |
| Project Header           | 0x00000000 (512 B)                    | 0x00000000 (512 B)                    |
| Patterns (128 Slots)     | 0x00000200 (Stride: 89,088 / 0x15C00) | 0x00000200 (Stride: 89,088 / 0x15C00) |
| Sound Kits (128 Kits)    | 0x00AE0200 (Stride: 10,752 / 0x2A00)  | 0x00AE0200 (Stride: 22,528 / 0x5800)  |
| Sound Pool (128 Slots)   | 0x00C32C04 (Stride: 359 / 0x167)      | 0x00DA0200 (Stride: 1,109 / 0x455)    |
| Sample Pool (1024 Slots) | _N/A (FM Synth Engine)_               | 0x00DC0600 (Stride: 32 / 0x20)        |
| Master Globals           | 0x00C3E000 (512 B)                    | 0x00DC8600 (4,864 B / 0x1300)         |
| Master Send FX           | 0x00C3E200 (3,072 B)                  | Kit +0x458C (160 B)                   |
| Song Mode (16 Songs)     | 0x00C3EE00 (Stride: 3,072 / 0xC00)    | 0x00DCD400 (Stride: 3,072 / 0xC00)    |
| End Magic Terminator     | 0x00C4AE00 (0xBACEF00C)               | 0x00DD9400 (0xBACEF00C)               |

---

## 3. Pattern Container Sub-Block Layout (0x15C00 / 89,088 bytes)

```
Pattern Container (89,088 bytes / 0x15C00)

├── +0x0000: 4-byte Format Version (DN2: 0x00000003, DT2: 0x00000004)
├── +0x0004: 16 Track Sequencer Structure-of-Arrays (SOA)
│ ├── DN2 Track Stride: 1,187 bytes (0x4A3) -> Total: 18,992 B
│ └── DT2 Track Stride: 1,184 bytes (0x4A0) -> Total: 18,944 B
├── Sparse Note Pool: (8,192 entries x 6 bytes = 49,152 bytes / 0xC000)
│ ├── DN2 Offset: +0x4A34
│ └── DT2 Offset: +0x4A04
├── Parameter Lock Pool: (80 slots x 258 bytes = 20,640 bytes / 0x50A0)
│ ├── DN2 Offset: +0x10A34
│ └── DT2 Offset: +0x10A04
└── Pattern Master Config Block: (40 bytes / 0x28)
    ├── DN2 Offset: +0x15AD4
    └── DT2 Offset: +0x15AA4
```

---

## 4. Track Sequencer SOA Step Arrays (128 Steps per Track)

### Digitone II (DN2) Track SOA (Stride: 1,187 B / 0x4A3)

- +0x000 .. +0x0FF: 16-bit Trig State Mask (128 BE words: 0x0381 = Active, 0x0391 = Active + Plocked)
- +0x100 .. +0x17F: Trig Condition (0..79, 0xFF = NONE)
- +0x180 .. +0x1FF: Retrig & Fill Modifiers (0xFF = OFF)
- +0x200 .. +0x27F: Chance / Probability (0..100%, 0xFF = 100%)
- +0x280 .. +0x2FF: Gate Length Override (0..127 Gate Index, 0xFF = Inherit default)
- +0x300 .. +0x37F: Velocity Override (1..127, 0xFF = Inherit default)
- +0x380 .. +0x3FF: Pitch Modifier (signed int8, 0xFF/0x00 = 0)
- +0x400 .. +0x47F: Sound Lock / Preset ID (0..127, 0xFF = NO SOUND LOCK)
- +0x480: Root Note Pitch (default 60 / C5)
- +0x481: Default Velocity (100)
- +0x482: Default Gate Length (14 = 1.0 step)
- +0x485: Track Transpose offset (signed int8)
- +0x48C: 16-bit Track Step Length (1..128, default 16)
- +0x48F: Speed Multiplier Index (0..6, default 2 = 1x)

### Digitakt II (DT2) Track SOA (Stride: 1,184 B / 0x4A0) — Grounded in FUN_400de8c6

- +0x000 .. +0x0FF: 16-bit Trig State Mask (128 BE words: 0x0381 = Active, 0x0391 = Active + Plocked)
- +0x100 .. +0x17F: Trig Condition (0..79, 0xFF = NONE)
- +0x180 .. +0x1FF: Retrig & Fill Modifiers (0xFF = OFF)
- +0x200 .. +0x27F: Chance / Probability (0..100%, 0xFF = 100%)
- +0x280 .. +0x2FF: Velocity Override (1..127, 0xFF = Inherit default)
- +0x300 .. +0x37F: Gate Length Override (0..127 Gate Index, 0xFF = Inherit default)
- +0x380 .. +0x3FF: Pitch Modifier (signed int8, 0x00 = 0)
- +0x400 .. +0x47F: Microtiming Offset (signed int8, 0xFF/0x00 = 0)
- +0x480: Root Note Pitch (default 60 / C5)
- +0x481: Default Velocity (100)
- +0x482: Default Gate Length (14 = 1.0 step)
- +0x48C: 16-bit Track Step Length (1..128, default 16)
- +0x48F: Speed Multiplier Index (0..6, default 2 = 1x)
- +0x492: Euclidean Sequencer Step Length (1..16, 0xFF = OFF)
- +0x493: Euclidean Pulse Count (0..16)
- +0x494: Euclidean Rotation offset (signed int8)

---

## 5. Sparse Note Pool (6-Byte Tuples)

Located at pat_base + 0x4A34 (DN2) / pat_base + 0x4A04 (DT2):

### Digitone II (Independent Absolute Polyphony)

- Byte 0: Track Index (0..15)
- Byte 1: Step Index (0..127)
- Byte 2: Absolute MIDI Pitch (0..127)
- Byte 3: Velocity Override (1..127, 0xFF = default)
- Byte 4: Gate Length Index (0..127, 0xFF = default)
- Byte 5: Microtiming Offset (signed int8, -23..+23)

### Digitakt II (4-Tuple Aligned Chord Blocks) — Grounded in FUN_400dff92

- Voice 0 (Root):
  - Byte 0: Track Index (0..15)
  - Byte 1: Step Index (0..127)
  - Byte 2: Root Note Pitch (0..127)
  - Byte 3: Velocity Override
  - Byte 4: Gate Length Index
  - Byte 5: Microtiming Offset
- Voices 1 .. 3 (Secondary Voices):
  - Byte 0: Track Index (0..15)
  - Byte 1: Step Index (0..127)
  - Byte 2: Interval Offset = 64 + (voice_pitch - root_pitch) (0xFF if unused)
  - Byte 3: 0xFF (Inherits Voice 0 Velocity)
  - Byte 4: 0xFF (Inherits Voice 0 Gate Length)
  - Byte 5: Microtiming Offset

---

## 6. Pattern Master Config Block (40 bytes / 0x28)

Located at pat_base + 0x15AD4 (DN2) / pat_base + 0x15AA4 (DT2):

- +0x10: Assigned Kit Index (0..127, 16-bit BE)
- +0x12: Pattern BPM (16-bit BE: raw = BPM \* 120, e.g. 14400 = 120.00 BPM)
- +0x14: Master Step Length (16-bit BE, 1..128)
- +0x18: Pattern Swing (0..31 -> 50%..81%)
- +0x19: Scale Mode (0 = Global, 1 = Per-Track)
- +0x1A: Pattern Speed Multiplier (0..6, default 2 = 1x)

---

## 7. Kit Containers & Sound Preset Memory Layout

### Digitone II Kit (Stride: 10,752 B / 0x2A00)

- +0x003C: 16 Track Sound Presets (16 x 359 B = 5,744 B / 0x1670)
  - Sound Preset +0x0C .. +0x1B: Sound Name (16 bytes ASCII)
  - Sound Preset +0xB0: Filter 1 Cutoff (0..127)
  - Sound Preset +0xB1: Filter 1 Type (0=Off, 1=LP2, 2=LP4, 3=HP, 4=BP)
  - Sound Preset +0xF4: Machine Engine (0=FM Tone, 1=WaveTone, 2=FM Drum, 3=Swarmer, 4=MIDI)
- +0x16AC: Master Send FX Block (160 bytes: Delay, Reverb, Chorus, Compressor)
- +0x174C: 16 Track Mixers / CC Pages (16 x 268 B = 4,288 B)
- +0x280C: Voice Allocation Matrix & Master Dynamics (244 bytes)

### Digitakt II Kit (Stride: 22,528 B / 0x5800) — Grounded in FUN_400de36e

- +0x001C .. +0x003B: 16 Track Level Scalars (16 x u16 BE, default 0x6400 = 100)
- +0x003C: 16 Track Sound Presets (16 x 1,109 B = 17,744 B / 0x4550)
  - Sound Preset +0x0C .. +0x1B: Sound Name (16 bytes ASCII)
  - Sound Preset +0xD2: Machine Type (0=Oneshot, 1=Werp, 2=Stretch, 3=Repitch, 4=Grid, 5=MIDI, 6=Slice)
  - Sound Preset +0xD3: Filter 1 Type (0=Multi, 1=LP4, 2=EQ, 3=Comb-, 4=Comb+, 5=Legacy)
  - Sound Preset +0x139 .. +0x438: 64 Custom Slice Markers (64 x 12 B = 768 B / 0x300)
- +0x458C: Master Send FX Block (160 bytes)
- +0x462C: 16 Track Mixers & 16 Assignable MIDI CCs (16 x 268 B = 4,288 B)
- +0x56EC: Master Compressor & Sidechain Bus Matrix (276 bytes)
- +0x573A: 4-byte Kit Footer Magic 0xBACEF00C

---

## 8. Master Globals & Song Mode

### Globals (0x00C3E000 on DN2 / 0x00DC8600 on DT2)

- +0x00: 32-bit Global Tempo (raw = BPM \* 120)
- +0x07: Global Swing (0 -> 50%)
- +0x14: Metronome Enabled (1 = On, 0 = Off)
- +0x15: Metronome Time Signature (1 = 6/8, 2 = 3/4, 3 = 4/4)
- +0x17: Metronome Preroll (0 = Off, 1 = 1 Bar, 2 = 2 Bars)
- +0x18: Metronome Volume (0..127)

### Song Mode (Stride: 3,072 B / 0xC00 x 16 Songs)

- Rows Array Offset: Song Base + 0x14 (99 Rows x 29 bytes / 0x1D = 2,871 B)
- Active Row Count Sentinel: Song Base + 0x0B4B (or +0x0E61)
- 29-byte Song Row Structure:
  - Byte 0: Pattern Index (0..127 -> Bank A..H, Pat 01..16)
  - Byte 2: Repeat Count (1..99)
  - Byte 3..6: 32-bit BPM Override (raw = BPM \* 120, 0 = Inherit pattern BPM)
  - Byte 7..8: 16-Track Mute Bitmask (Bit 0..15 = Track 1..16 Muted)
  - Byte 9..10: Row Step Length (1..1024 steps)

---

## 9. Pattern Custom Names (Tag 1 / PTN NAME)

**exact functions, offsets, and data structures** responsible for resolving Tag `1` (`(PTN NAME)`).

### 9.1 Grounded Execution Trace of Dynamic Tag 1

In `FUN_4007e970` (Playlist Row Drawer) and `FUN_40081192` (Cue Row Drawer):

```
// 1. Read Row Tag ID and Pattern Index
uVar8  = FUN_40049a26(song, row_idx);   // Tag ID from Row (+0x01 on disk / +0x18 in RAM)
uVar11 = FUN_40049716(song, row_idx);   // Pattern Index from Row (+0x00 on disk / +0x10 in RAM)

// 2. Fetch the Pattern object for that pattern index
uVar2 = FUN_4003dcc6(proj, uVar11); // Pattern Object (Stride: 0x954 RAM / 0x15C00 Container)
uVar2 = FUN_4003ac2c(uVar2); // PatternSettings sub-object (+0x2C in RAM)

// 3. If Tag ID == 1: Resolve the dynamic pattern name!
if (uVar8 == 1) {
    FUN_4003a976(uVar2); // Reads 16-byte custom pattern name string
    // Truncates to fit UI column (6-9 chars)
} else {
    // Look up static enum in table (Tags 2..20)
    label = (&PTR_DAT_40272d14)[uVar8];
}
```

### 9.2 Exact Memory Offsets for Pattern Custom Names

In `FUN_40039b82`, `PatternSettings` is unpacked directly from the Pattern Config Block at the end of each pattern slice:

#### Digitone II (.dn2prj)

- **Pattern Base**: `PATTERN_1_BASE + (pat_idx * 0x15C00)` (where `PATTERN_1_BASE = 512`)
- **Pattern Config Offset**: `pat_base + 0x15AD4`
- **Custom Pattern Name String Buffer**: `pat_base + 0x15AD4 + 0x00` through `+0x0F` (16 bytes ASCII)
- **Pattern Config Structure**:
  - `+0x00 .. +0x0F`: **16-Byte Custom Pattern Name** (null-terminated ASCII)
  - `+0x10 .. +0x11`: Kit Index (`uint16_be`)
  - `+0x12 .. +0x13`: Pattern BPM (`uint16_be`)
  - `+0x14 .. +0x15`: Pattern Step Length (`uint16_be`)
  - `+0x18`: Scale Mode / Swing

#### Digitakt II (.dt2prj)

- **Pattern Base**: `OFFSET_PATTERNS_BASE + (pat_idx * 0x15C00)` (where `OFFSET_PATTERNS_BASE = 512`)
- **Pattern Config Offset**: `pat_base + 0x15AA4`
- **Custom Pattern Name String Buffer**: `pat_base + 0x15AA4 + 0x00` through `+0x0F` (16 bytes ASCII)
- **Pattern Config Structure**:
  - `+0x00 .. +0x0F`: **16-Byte Custom Pattern Name** (null-terminated ASCII)
  - `+0x10 .. +0x11`: Kit Index (`uint16_be`)
  - `+0x12 .. +0x13`: Pattern BPM (`uint16_be`)
  - `+0x14 .. +0x15`: Pattern Step Length (`uint16_be`)
  - `+0x18`: Scale Mode / Swing

### 9.3 Resolution Logic for Tag 1

```
def get_pattern_name(self, pattern_idx: int) -> str:
    pat_base = self._pattern_base(pattern_idx)
    cfg_offset = pat_base + PATTERN_CONFIG_OFFSET  # 0x15AD4 on DN2, 0x15AA4 on DT2
    raw_name = self.ram[cfg_offset : cfg_offset + 16].decode("cp1252", errors="ignore").split("\x00")[0].strip()
    if raw_name:
        return raw_name  # Fallback to standard Pattern Bank/Number if unnamed
    bank_letter = chr(ord('A') + (pattern_idx // 16))
    pat_num = (pattern_idx % 16) + 1
    return f"{bank_letter}{pat_num:02d}"
```

When a Song Row has `tag_id == 1`:

1. If the user assigned a custom name to that pattern (e.g. `"INTRO BEAT"` at `pat_base + CONFIG + 0x00`), Tag `1` displays `"INTRO BEAT"`.
2. If the pattern name is blank/unassigned, Tag `1` displays the pattern coordinate (e.g. `"A01"`).
