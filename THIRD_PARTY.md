# Third-party notices

ReWatch(Iot)'s own source is Apache-2.0-licensed — see [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE).

It also **bundles and depends on software that is not ours**. Those licences are
listed here because several of them require the notice to travel with the code.

**If you redistribute ReWatch(Iot) — a built dashboard, a disk image, a booth SD card,
a tarball — this file must travel with it.** It is not decoration; the SIL Open
Font License in §1 is only satisfied if the licence text and copyright notice
accompany the font files.

Nothing here is legal advice. It is an inventory, so that the person doing the
redistributing can check it.

---

## 1. Font Software — SIL Open Font License 1.1

The dashboard self-hosts Newsreader, Schibsted Grotesk and JetBrains Mono under
`pi4-core/web/assets/fonts/`, also copied into the Black Hat workspace. The IBM Plex
notice below is retained from earlier work; no IBM Plex binary is currently
served. There is no font CDN or font build step in this repository.

Subsetting is mechanical: glyph subset plus woff2 re-encode. No glyph outlines are
redrawn and no family or reserved font name is changed. The derivatives therefore
stay under the OFL, as condition 5 requires.

### Newsreader

- Used for: the wordmark and display headings
- Upstream: <http://github.com/productiontype/Newsreader>
- Files served: `newsreader-*` (latin subset, weights as built)

```
Copyright 2020 The Newsreader Project Authors (http://github.com/productiontype/Newsreader)
Newsreader-Italic[opsz,wght].ttf: Copyright 2020 The Newsreader Project Authors (http://github.com/productiontype/Newsreader)
```

### Schibsted Grotesk

- Used for: UI and body text
- Upstream: <https://github.com/schibsted/schibsted-grotesk>
- Files served: `schibsted-grotesk-*` (latin subset, weights as built)

```
Copyright 2023 The Schibsted-Grotesk Project Authors (https://github.com/schibsted/schibsted-grotesk)
SchibstedGrotesk-Italic[wght].ttf: Copyright 2023 The Schibsted-Grotesk Project Authors (https://github.com/schibsted/schibsted-grotesk)
```

### JetBrains Mono

- Used for: telemetry, MACs, scores, and every other monospaced field
- Upstream: <https://github.com/JetBrains/JetBrainsMono>
- Files served: `jetbrains-mono-*` (latin subset, weights as built)

```
Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)
JetBrainsMono-Italic[wght].ttf: Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)
```

### IBM Plex Sans

- Used for: numeric and tabular readouts
- Upstream: <https://github.com/IBM/plex>
- Files served: `ibm-plex-sans-*` (latin subset, weights as built)

```
Copyright 2019 IBM Corp. All rights reserved.
```

### Licence text

These fonts are licensed under the SIL Open Font License, Version 1.1, reproduced
here in full as the licence requires. The original is available with a FAQ at
<https://scripts.sil.org/OFL>.

```
-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

---

## 2. Python packages — runtime

Pinned in `requirements.txt`; role code uses the relevant subset.

| Package | Version | Licence |
|---------|---------|---------|
| aiohttp | 3.14.5 | Apache-2.0 |
| aiomqtt | 2.5.1 | BSD-3-Clause |
| webauthn | 2.8.0 | BSD-3-Clause |
| paho-mqtt | 2.1.0 | EPL-2.0 OR BSD-3-Clause |
| pyserial | 3.5 | BSD-3-Clause |
| scapy | 2.8.0 | GPL-2.0-only |

Not resold and not modified; installed from wheels by `pip` at deploy time. The
Apache-2.0 packages include their own `NOTICE` files inside the wheels, which
`pip` installs alongside them.

## 3. Python packages — development and test only

Pinned in `requirements-dev.txt`. **Not present on a deployed Pi.**

| Package | Version | Licence |
|---------|---------|---------|
| pytest | 9.1.1 | MIT |
| ruff | 0.17.1 | MIT |
| playwright | 1.64.0 | Apache-2.0 |

`paho-mqtt` is dual-licensed; ReWatch(Iot) uses the BSD-3-Clause option. WebAuthn also
installs transitive packages such as `cbor2` (MIT) and `cryptography`
(Apache-2.0 OR BSD-3-Clause). Retain their installed license notices when
redistributing an environment. Scapy is imported by Sentinel: review its GPL
obligations before distributing a combined deployment or disk image; this file
does not resolve legal questions about derivative works.

## 4. Frontend and firmware dependencies

The shipped dashboard is plain HTML/CSS/JavaScript: no React, Vite, npm build or
runtime JavaScript package is required. ULTRON and VoidMain were read-only design
references, not runtime dependencies.

PlatformIO downloads ArduinoJson (MIT), PubSubClient (MIT), Adafruit NeoPixel
(LGPL-3.0), Adafruit GFX and SSD1306 (BSD), and ESP32 Arduino/platform tooling.
See each downloaded package's license and the versions in `platformio.ini`.
Compiled firmware includes third-party code; comply with those licenses when
redistributing binaries. Build directories and downloaded sources are ignored.

---

## 5. Programs ReWatch(Iot) invokes but does not link, modify or redistribute

This is the licensing boundary that matters most for ReWatch(Iot), and it is deliberate.

| Program | Licence | How ReWatch(Iot) uses it |
|---------|---------|--------------------|
| **Mosquitto** | EPL-2.0 | Its own daemon; ReWatch(Iot) is an MQTT *client* over TCP:1883. |
| **nftables / nft** | GPL-2.0 | Its own binary; ReWatch(Iot) applies rules through `nft` and the kernel. |

ReWatch(Iot) does not link against these, does not patch them, and does not ship them
in this repository. It talks to them across a process boundary or a socket. As a
consequence **their licences do not reach ReWatch(Iot)'s own source**, and ReWatch(Iot)'s
Apache-2.0 licence does not reach them.

The practical consequences, which are worth knowing before you build a booth image:

- If you **redistribute a disk image** with nftables or Mosquitto already
  installed, you are the one distributing GPL-2.0 and EPL-2.0 binaries. Ship
  their licences and, for the GPL-2.0 programs, be ready to supply the
  corresponding source and build information where required.
- If you only **document** `apt-get install mosquitto nftables`, no
  redistribution happens and no obligation attaches to you.
- This repository supplies installer scripts, not OS images or vendored daemon
  binaries. Follow the [installation guide](README.md#physical-installation).

---

## 6. Deliberately absent

ReWatch(Iot) has **no runtime JavaScript package dependency**. The dashboard has no
CDN `<script>`, no font CDN, no analytics, no telemetry. That is a security
property before it is a licensing one — see the CSP notes in
[`SECURITY.md`](SECURITY.md) — but it also means the browser-side third-party
surface is close to empty.
