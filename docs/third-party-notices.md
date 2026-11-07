# Dependency notices

The application uses original project code plus open-source dependencies; retain the dependencies' copyright and license notices when redistributing binaries.

| Component | Pinned version | Declared license / authoritative source |
|---|---|---|
| AsyncSSH | 2.24.1 | EPL-2.0 OR GPL-2.0-or-later; https://github.com/ronf/asyncssh |
| bcrypt | 5.0.0 | Apache-2.0; https://github.com/pyca/bcrypt |
| pySerial | 3.5 | BSD; https://github.com/pyserial/pyserial |
| pyte | 0.8.2 | See license at https://github.com/selectel/pyte |
| PySide6 / Qt | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only; https://www.qt.io/licensing/open-source-lgpl-obligations |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause; https://github.com/pyca/cryptography |

`requirements-lock.txt` pins the full current dependency set. The table is a navigation aid, not a substitute for license texts or a complete Qt third-party inventory. Before distributing a Windows bundle, collect the license texts, identify included Qt modules and their third-party components, and satisfy the selected licenses' distribution and replacement requirements. Current output is an unsigned internal development build; release compliance has not been reviewed.

Craft Anything is installed as a separate tool and is not embedded into Harbor Terminal. Its source checkout retains its MIT/Apache license and notices unchanged.
