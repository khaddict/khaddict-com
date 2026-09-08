FROM alpine:3.24 AS builder
RUN apk add --no-cache vips-tools imagemagick
COPY media/ /data/
COPY process-icons.sh /tmp/process-icons.sh
RUN chmod +x /tmp/process-icons.sh && /tmp/process-icons.sh && rm -f /data/icons/no-outline
RUN rm -f /data/videos/README.md
RUN mkdir -p /data/icons/thumbs /data/gallery/thumbs \
 && find /data/icons -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) \
      -exec sh -c 'vipsthumbnail "$1" --size 90x90 -o "/data/icons/thumbs/$(basename "$1")"' _ {} \; \
 && find /data/gallery -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) \
      -exec sh -c 'vipsthumbnail "$1" --size 800x600 --crop=centre -o "/data/gallery/thumbs/$(basename "$1")[Q=80]"' _ {} \;
      # Q=80 is a JPEG/WEBP save option; libvips ignores it for the .png sources in this folder

FROM nginx:1.31.5
COPY --from=builder /data/ /data/
