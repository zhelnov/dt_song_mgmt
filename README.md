# dt_song_mgmt

Dump and restore Digitakt II song slots from an Elektron Transfer `.dt2prj` file.

Transfer stores the project as LZ4-compressed 32 KiB blocks, not raw song bytes. This script decompresses the project, copies the 16 uncompressed song slots (3072 bytes each), and recompresses on restore so the device can import the file.

Python 3. Requires nothing extra; `liblz4` is used if present.

## Dump

```bash
python ./dt_song_mgmt.py project.dt2prj
```

Writes 16 files to `./SONGS_<stem>/`, plus a setlist page:

```
00_<name>.bin ... 15_<name>.bin
songs.html
```

## Restore

Overwrites the `.dt2prj` (writes a `.bak` first for backup):

```bash
python ./dt_song_mgmt.py project.dt2prj ./SONGS_<stem> NEW_NAME
```

`NEW_NAME` is the project name stored in the `.dt2prj` payload, not just the file or folder name.

Files are matched by the `NN_` slot prefix (`00`–`15`). Missing slots are cleared to empty songs — the folder is treated as the full 16-slot setlist.
