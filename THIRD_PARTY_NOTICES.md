# Third-party notices

## Newflasher

- Upstream: https://github.com/munjeni/newflasher
- Pinned commit: `59f12e437d29f0385eb27dcebba5158aa3f97b45`
- Source: https://github.com/munjeni/newflasher/blob/59f12e437d29f0385eb27dcebba5158aa3f97b45/newflasher.c
- Vendored file: `flash-kit/upstream/newflasher-59f12e4.c.txt`
- SHA-256: `79804a4df5a35e507a96df827083ca3eac3f70d068223ca2a70246f4ad2f9e17`
- Copyright (c) 2017 Munjeni
- License: MIT (upstream copyright and full permission notice are retained in the source).

The vendored file is kept byte-for-byte unchanged. `flash-kit/build_trial.py`
checks its digest, transforms selected SIN/USB transport code, and combines it
with this project's policy and entry-point templates. The generated executable
is an experimental project-specific derivative, not unmodified Newflasher and
not an official Sony tool. Generated source retains the upstream notice.

### Upstream MIT license

Copyright (c) 2017 Munjeni

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Firmware and external dependencies

Sony firmware, Qualcomm/Google/Sony components extracted from firmware,
Android platform tools, XperiFirm, libusb, OpenSSL (Linux SHA-256), compiler/SDK libraries, ax and Python
packages are not distributed in this repository. They retain their respective
licenses. This project's MIT license does not relicense those materials.

Build binaries locally. Before distributing binaries or bundling dependencies,
review the relevant third-party distribution obligations separately.
