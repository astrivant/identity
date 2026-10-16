## Release details

Install the package with `pip install witful` or `pip install 'witful[postgres]'`.

Download the distributions, public key, fingerprint, manifest, and Sigstore bundles.
Compare the fingerprint with a trusted source, then verify:

```bash
cosign verify-blob --key cosign.pub --bundle SHA256SUMS.sigstore.json SHA256SUMS
sha256sum --check SHA256SUMS
```

SOURCE.json identifies the tag and source commit used for the distributions.
