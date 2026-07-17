# curl/libcurl reads CURL_CA_BUNDLE at runtime as its default CA store.
# Point it at the vendored bundle on the read-only cramfs (curl's compiled-in
# default is not honored on this build, and /etc/ssl is not shipped).
export CURL_CA_BUNDLE=/usr/share/ca-certificates/ca-bundle.crt
