# Security policy

## Reporting a vulnerability

**Please do not report it in public.** Use GitHub's private vulnerability
reporting on this repository: the **Security** tab, then *Report a
vulnerability*. It reaches only the maintainer and does not require
exchanging email addresses. If it is unavailable to you, get in touch through
**[radioterapia.ai](https://radioterapia.ai)** and say only that you have a
security report; the details can then move to a private channel.

**Never attach patient data**, here or anywhere else: no DICOM series, no
CD image, no screenshot of a patient image, no log with a patient ID, a UID
or a series path. Describe the problem in words, or reproduce it with the
synthetic phantoms the batteries build.

## What is in scope

The code in this repository: reading exams from files, folders and CDs, the
diagnosis, the conversion and the delivery. The installer, the updater and
the shell shared by the six apps live in the
[Local Suite](https://github.com/radioterapia-ai/local-suite) repository; a
finding there can be reported here or there. The exported series carries the
patient's identification on purpose, so the findings that matter most are the
ones that move it where it should not go:

- Anything that lets the export land in a folder that syncs to the cloud, or
  sends anything off the workstation.
- Anything that writes to the source being read, a CD or a folder.
- Anything that puts a patient's folder path in a URL, or identification in
  the conversion receipt.

The libraries this app uses are their authors' work: a problem in one of them
belongs with its authors.

## Not a medical device

Teaching and research material, not a medical device, not validated for
clinical use: a clinically wrong result is a correctness bug, not a
vulnerability, and is welcome through
**[radioterapia.ai](https://radioterapia.ai)**, without patient data.

## Supported versions

The latest Local Suite release, and the tag of this app that it pins.
Single maintainer, no backports.
