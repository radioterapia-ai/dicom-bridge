# DicomBridge

**Part of the Radioterapia.AI Local Suite. DicomBridge: inspects and converts external exam files for the treatment planning system — teaching and research material, not a medical device.**

`License: Apache-2.0` · `Component of: Radioterapia.AI Local Suite` · `Platform: Windows 10 and 11, 64-bit`

> **Teaching and research material. This is not a medical device.**
> It is **not** validated for clinical use, and it has no ANVISA registration,
> no CE mark and no FDA clearance. It inspects and converts exam files; it
> does not diagnose and it decides nothing clinical. A converted series must
> be checked in the planning system — that it belongs to the right patient,
> and that its fusion is registered rather than assumed. Every structure the
> suite writes for a series sent from here is an **unapproved suggestion**;
> reviewing and approving it is a physician's act, in the planning system.

## What it does

An exam from another service often fails to import into the planning
system — a colour image, a secondary capture without the attributes the
standard requires, a compressed transfer syntax, a series that arrived as
JPEG pictures. DicomBridge is the module of the suite that shows what stops a
study from being accepted and converts it so that it is.

It has one tool, inside the suite — **Convert images for the TPS**, one
vertical page that opens step by step:

1. **Load** — a folder, files, a `.zip`, drag and drop, **Load a CD**,
   which finds the CD drive with a disc and reads the whole disc, folders and
   subfolders, without writing anything to it (the CD is never offered as a
   destination, and the reading can be cancelled), or **Import image**, which
   opens the Windows file dialog filtered to the pictures it reads (JPEG,
   PNG, TIFF and BMP). A folder is read in the background by the Suite's
   reader, with *Stop reading*: the series appear as they are found, each
   with the thumbnail of its middle slice, and what was read goes straight
   to the diagnosis, which does not read the study again. Unlike the other
   modules, it reads with no date filter: a CD or an outside exam brings old
   folder dates. What is sent is
   copied to a working folder on this workstation, outside any synced folder,
   with short names (long DICOM UIDs would pass the Windows path limit), and
   deleted when the loads are cleared, when the app closes, or after 12 hours.
2. **Choose** the series and, for each one, the segmentation: none, FAST, AUTO
   or CUSTOM, with its tasks. A click marks a series; a double click opens it
   with its header.
3. **Diagnostics** — alerts only. Two things stop the conversion of a DICOM
   series: a compression this installation cannot decode, and a slice whose
   image is incomplete in the file (it would reach the planning system
   corrupted). Anything else converts, and what the conversion does not fix
   is written inside the DICOM itself, in the series description and the
   image comments. No question is asked about text burned into the pixels;
   it stays an alert.
4. **Convert** — every series comes out uncompressed, in Implicit VR Little
   Endian (the default DICOM transfer syntax, the same one the RTSTRUCT uses,
   whichever ring drawing is set in *Settings → General*), with the UIDs it
   brought
   — except a colour series, written in greyscale (`MONOCHROME2`), and a
   series whose slice position or orientation the conversion had to assume:
   those get new UIDs, so they never mix with the original. A series without
   a Frame of Reference, or with its geometry assumed, gets a new Frame of
   Reference, and a secondary capture gets its `ConversionType`; each forced
   choice goes into the DICOM as an alert.
5. **Deliver** — always into a new folder, `DICOM_BRIDGE_<date_time>`, in
   Downloads or in the destination chosen, copied to the other destinations.
   A folder recognised as synced to the cloud, and the folder the night
   watcher processes, are refused.
6. **Segment**, if asked — the series goes to the end of the hand‑entered part
   of the workstation's single queue, with the tasks chosen; ContourLab runs
   it, and the RTSTRUCT is written beside the delivered series, in the first
   destination, and copied to the others. The card stays in view until the
   RTSTRUCT arrives.

**An exam that arrived as pictures** (JPEG or PNG; TIFF and BMP are read
too) goes through the same pipeline, without segmentation: its series is a
card in the same grid, its adjustment lives in the diagnosis step, and it is
converted and delivered together with the DICOM series, in the same new
folder, each picture series with its own generated ID:

- A JPEG keeps no millimetres per pixel, no slice thickness and no
  orientation. The scale and the thickness come suggested; the thickness is
  mandatory, and the spacing between slices sits next to it (empty, it is
  the thickness). The suggested scale assumes the typical field of the
  modality, so a picture exported with zoom comes out flattened: **Measure a
  known distance** takes two clicks on the axial over a line of known
  length, such as the ruler burned into the image, and its length in
  millimetres, and the scale comes out of that.
- The default assumes the first file is at the feet (for a coronal series,
  at the front; for a sagittal one, at the patient's left). **Reverse the
  slice order** fixes a series exported the other way, in the MPR and in
  the exported DICOM; a picture has no slice position, so the direction is
  not detected.
- The MPR is drawn in the standard presentation for an axial, a coronal or
  a sagittal series, from the same orientation that goes into the exported
  DICOM, and its edges say where the patient is: cranial at the top and
  caudal at the bottom of the coronal and the sagittal, the patient's right
  on the left of the coronal, anterior on the left of the sagittal. The
  labels belong to the presentation, not to the files: reversing the order
  flips the image and the labels stay, so the head should end up next to
  "cranial".
- One click confirms that the scale and the slice order were checked on an
  MPR that shows whether the volume was distorted: round things come out
  round, and the head is up in the coronal and the sagittal. Changing the
  scale or reversing the order asks for it again, and the conversion waits
  for it. A wrong scale puts an image of the wrong size into the fusion, a
  reversed order puts in a mirror image, and a rigid registration corrects
  neither.
- Pictures of different sizes do not convert as one series: a DICOM series
  has a single matrix.
- The orientation is read from the series description ("MR t2 axial" is
  axial), for the person to check.
- A picture does not say whose it is: the series comes out as patient
  `DESCONHECIDO` ("unknown"), with a generated ID
  (`EXTERNO-<date>-<time>-<random suffix>`) that never repeats, and the delivery folder carries a one‑line `LEIA-ME.txt`
  asking for it to be assigned to the right patient in the planning system.
  In the planning system an unknown series may become a new patient or be
  attached to the wrong one; that responsibility is whoever imports it.
- Text burned into the pixels by a viewer is not cropped — cropping would
  change the geometry of the fusion. It becomes an alert.
- The series is born with a **new Frame of Reference, always**, so that the
  planning system demands a registration instead of assuming alignment, and
  it carries no Hounsfield units: the grey of a JPEG is a display level.

## What it does not do

- It does not resample slices and does not drop duplicates. A DICOM series
  keeps the UIDs and the Frame of Reference it brought, unless the conversion
  changed its pixels or assumed its geometry (new UIDs) or it had no Frame of
  Reference (a new one).
- It does not promise Hounsfield units for what it converts from a picture.
- It does not mark, highlight or list findings: it shows the image and the
  header.
- It finds DICOM by content (the `DICM` marker, or the opening group of a
  file without preamble), never by extension: DICOM from a CD has no
  extension, and a work disk has `.zip` and `.dll` files.

## What is ours, and what is not

DicomBridge uses no model and no weight. DICOM is read and written with
[pydicom][pydicom] (MIT), through the Suite's shared DICOM layer, which also
holds the conversion rules; the thumbnail is a PNG written with `zlib`. The
segmentation of a series sent from here is ContourLab's, through the Suite's
queue, and the third‑party models it runs are credited in ContourLab's
`NOTICE`. These libraries are installed by the Suite's preparer and do not
travel in this repository.

## Privacy

Nothing leaves the workstation on its own. The exported series **carries the
patient's name, record number and birth date** — it is meant for the planning
system of the same service —, so the destination cannot be a folder synced to
the cloud, and the program refuses one it recognises as such. The receipt of a
conversion carries no identification (not even the series description, a
free‑text field where people type names). The folder path of an exam stays in
the server process: the screen refers to a series by an opaque ticket, never
by the patient's path in the URL.

## Part of the Local Suite

DicomBridge does not run on its own. The shared shell — the entrance page,
the menus, the twelve languages, the Terms and the Privacy Policy, the
configuration, the case archive, DICOM reading, the viewers and the queue —
lives in the [Suite][suite], and on the workstation the suite is one program:
one process, one port, one `app` folder, assembled by the Suite's installer
from the seven repositories.

To use it, install the Suite with its light installer, from the
[releases of drhenriquebraga/local-suite][rel] (the permanent link to the
newest one is [`RADIOTERAPIA_AI_LOCAL_SUITE_SETUP_LATEST.zip`][latest]);
requirements and installation are in the Suite README.

This repository has no build of its own. The Suite's packager
(`build/empacotar_instalador.py --dos-repositorios`) downloads each component
at the tag pinned in `build/componentes.lock.json`, checks the SHA‑256 of its
extracted tree against the lock and
assembles the installer — see *Build from source* in the Suite README.

## Running the batteries

The batteries (`tools/test_*.py`, listed in `componente.json`) run over
synthetic phantoms. **No patient data is used anywhere in this repository, and
none may be committed to it.**

1. Put the [Suite][suite] and the six component repositories side by side in
   one folder. Folder names do not matter: the Suite is the folder with
   `tools/_componentes.py`, and each component is found by its
   `componente.json` (or set `RADAI_COMPONENTES_DIR` to the folder that holds
   the components). The batteries import modules of the Suite and of the
   other components, so all seven are needed.
2. Create the Suite's development environment: a Python virtual environment
   in `.venv` at the Suite root, as its README describes.
3. Run every battery of this component:

   ```
   <suite>\.venv\Scripts\python.exe <suite>\tools\_componentes.py --verificar <this folder>
   ```

   or a single one, with `--rodar test_<name>.py`. Each battery ends with an
   `OK:` or a `FALHOU:` footer, and `--verificar` ends with how many failed.
   `verify.cmd`, in this folder, does the same in two clicks once
   `_python.txt` (ignored by Git) holds the path of that `python.exe`.

4. **Turn on the pre‑commit hook** (once per clone):
   `git config core.hooksPath .githooks`. It runs the Suite's
   patient‑data scan over what is staged and refuses the commit that
   carries DICOM (with or without extension), a medical volume or a run
   log — and refuses it too when the scan cannot run, without the Suite
   beside this folder or without Python.

## Reporting a problem

A problem that is not a vulnerability goes through
**[radioterapia.ai](https://radioterapia.ai)**. Include the Local Suite
version, the Windows version, the screen language and the step that
failed — and **never patient data**: no DICOM series, no screenshot of a
patient image, no log with a patient ID, a UID or a series path. A problem
reproduced with the synthetic phantoms of the batteries is the quickest to
fix.

## Security

Found something that exposes patient data or lets the program act where it
should not? **Do not report it in public.** Use GitHub's private
vulnerability reporting on this repository, described in
[SECURITY.md](SECURITY.md).

## Licence and name

The code is licensed under the [Apache License 2.0](LICENSE). As section 6
says, the licence grants no permission to use the trade names of the
Licensor — "Radioterapia.AI", "Local Suite" and "DicomBridge" included —
except as required to describe the origin of the work. A build you adapt is
yours: name it as yours.

| | Published code | A service's own build |
|---|---|---|
| What it is | Teaching and research material | An in‑house tool the service adapts, validates and registers in its own jurisdiction |
| Medical device? | **No.** Not validated for clinical use | Whatever that service's validation and registration make it |
| Who answers for it | Whoever downloads, modifies and deploys it answers for their own build, made with the Suite's build path | The service that deploys it |

Built by Dr. Henrique Braga, radiation oncologist —
**[radioterapia.ai](https://radioterapia.ai)**.

[pydicom]: https://github.com/pydicom/pydicom
[suite]: https://github.com/drhenriquebraga/local-suite
[rel]: https://github.com/drhenriquebraga/local-suite/releases
[latest]: https://github.com/drhenriquebraga/local-suite/releases/latest/download/RADIOTERAPIA_AI_LOCAL_SUITE_SETUP_LATEST.zip
