# Media hosting

Only the **Enhancor** provider needs publicly reachable media URLs. The **fal** provider uploads every local file to fal storage with `fal_client.upload_file` and never uses the hosts below; `MEDIA_HOST` and `MEDIA_HOST_FALLBACKS` are ignored when you submit through fal. Replicate preprocessing uses Replicate's `/v1/files` upload API with your token. URLs and request bodies stay in each local run folder.

## Tmpfiles (default)

`MEDIA_HOST=tmpfiles`. No account key required. The adapter POSTs multipart `file` and `expire=21600` (six hours) to `https://tmpfiles.org/api/v1/upload`, reads the response download page and extracts its actual `/dl/…` link (including host-generated path components), then verifies that it returns nonempty non-HTML bytes. Current documented maximum is 100 MB. Reference: [Tmpfiles API](https://tmpfiles.org/api).

Tmpfiles links are public while they exist, but they expire. Temporary files can disappear before a long queue finishes. Re-upload only for a deliberate new submission, after checking whether the original request completed. Do not requeue blindly.

## Catbox: off by default, opt-in only

**Catbox is PUBLIC and PERSISTENT.** Anything uploaded there stays reachable by anyone with the link, indefinitely. Puppeteer never uses Catbox unless you name it explicitly:

- `MEDIA_HOST=catbox` makes it the primary host, or
- `MEDIA_HOST_FALLBACKS=catbox` tries it after two failed Tmpfiles attempts.

The shipped `.env.example` leaves `MEDIA_HOST_FALLBACKS=` empty, so a Tmpfiles failure stops with an error instead of silently switching to a persistent public host. The first Catbox upload in a process emits a `warnings.warn` reminder. Optionally set your own `CATBOX_USERHASH` so uploads land in your account. Multipart POST to `https://catbox.moe/user/api.php` with `reqtype=fileupload`, optional `userhash`, and `fileToUpload`; the response is a direct URL. Reference: [Catbox API](https://catbox.moe/tools.php).

## Fallback behaviour

`MEDIA_HOST` selects the primary host (`tmpfiles` by default). `MEDIA_HOST_FALLBACKS` is a comma-separated list of additional hosts tried, in order, only after the primary fails twice; it is empty by default. The uploader warns when switching hosts and checks that the returned media URL serves real media bytes. It never retries model generation. Failed or expired media must be freshly uploaded before a separately authorized generation retry.

For private storage, replace `media_host.upload` with your own signed-URL uploader whose expiry covers the full generation queue, or use the fal provider. No storage credentials are included.
