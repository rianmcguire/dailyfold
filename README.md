# dailyfold

A daily outliner. GTK3, one markdown file per day.

Heavily inspired by [Logseq](https://logseq.com/)'s journal, and the files are (roughly) compatible.

## Installing

GitHub Releases include a noarch RPM for Fedora.

## Building

```
sudo dnf install rpm-build desktop-file-utils
scripts/build-rpm
```

The resulting package is written to `dist/`.

## License

Dailyfold is licensed under the GNU General Public License version 3. See
[LICENSE](LICENSE).
