TARGET="${HOME}/vault/projects/brain/"
cp README.md "${TARGET}/README.md"
rsync --recursive --delete --verbose docs/ "${TARGET}/docs"
rsync --recursive --delete --verbose img/*.png "${TARGET}/img"
