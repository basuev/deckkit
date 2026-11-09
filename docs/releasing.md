# Releases

The release version is `deckkit.__version__`. Package versions are in
`assets/catalog.json` and the corresponding package manifests. Keep a package's
catalog and manifest versions equal.

Build from a clean source revision using the Ubuntu 22.04 image:

```sh
make dev
make check
make test-ui
make release REPOSITORY=basuev/deckkit
```

The output under `dist/` contains the Desktop installer, portable runtime,
Cyberpunk package, catalog and SHA256SUMS. Publish only those five files as GitHub
release assets. The unpacked `runtime/` folder is a build output.

Check the hashes from the output directory:

```sh
cd dist
sha256sum --check SHA256SUMS
```

Check the Desktop entry with `desktop-file-validate` where available. The builder
pins its runtime URL and hash into the installer. Rebuild the installer whenever
the runtime archive or target repository changes. Keep published versioned
assets immutable. Ship changes under a new version.

The installer links and update catalog use GitHub's latest-release route. Use a
normal release for the current delivery design. A prerelease-only repository does
not provide the latest full-release route used by the application. See the
[GitHub release API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).

Before publishing, review the exact source revision, release description and
asset hashes. Remote repository creation, pushes and asset uploads require
explicit authorization. Building the files or preparing a local commit does not
publish anything. No workflow automatically publishes releases.
