/*
 * Minimal Mbed TLS configuration for the ESP32-S3 N8 client profile.
 *
 * Intended use:
 *   curl HTTP/HTTPS client
 *   TLS 1.2
 *   CA certificate verification
 *   RSA and ECDSA server certificates
 *   ECDHE-RSA / ECDHE-ECDSA
 *   AES-GCM
 *
 * This is intentionally a client-only configuration.
 */

#ifndef MBEDTLS_CONFIG_H
#define MBEDTLS_CONFIG_H

/* System support */
#define MBEDTLS_HAVE_TIME
#define MBEDTLS_HAVE_TIME_DATE
#define MBEDTLS_FS_IO

/* TLS 1.2 client */
#define MBEDTLS_SSL_PROTO_TLS1_2
#define MBEDTLS_SSL_CLI_C
#define MBEDTLS_SSL_TLS_C
#define MBEDTLS_SSL_SERVER_NAME_INDICATION

/* Key exchange used by normal HTTPS servers */
#define MBEDTLS_KEY_EXCHANGE_ECDHE_RSA_ENABLED
#define MBEDTLS_KEY_EXCHANGE_ECDHE_ECDSA_ENABLED

/* Elliptic curves */
#define MBEDTLS_ECP_DP_SECP256R1_ENABLED
#define MBEDTLS_ECP_DP_SECP384R1_ENABLED
#define MBEDTLS_ECP_NIST_OPTIM

/* Symmetric crypto */
#define MBEDTLS_AES_C
#define MBEDTLS_GCM_C
#define MBEDTLS_CIPHER_C

/* Hashes */
#define MBEDTLS_MD_C
#define MBEDTLS_SHA256_C
#define MBEDTLS_SHA512_C

/* Random number generation */
#define MBEDTLS_ENTROPY_C
#define MBEDTLS_CTR_DRBG_C

/* Public-key crypto */
#define MBEDTLS_BIGNUM_C
#define MBEDTLS_ECP_C
#define MBEDTLS_ECDH_C
#define MBEDTLS_ECDSA_C
#define MBEDTLS_RSA_C
#define MBEDTLS_PK_C
#define MBEDTLS_PK_PARSE_C
#define MBEDTLS_PK_WRITE_C
#define MBEDTLS_PKCS1_V15
#define MBEDTLS_PKCS1_V21

/* ASN.1 / OID */
#define MBEDTLS_ASN1_PARSE_C
#define MBEDTLS_ASN1_WRITE_C
#define MBEDTLS_OID_C

/* X.509 certificate parsing and verification */
#define MBEDTLS_X509_USE_C
#define MBEDTLS_X509_CRT_PARSE_C
#define MBEDTLS_X509_CHECK_KEY_USAGE
#define MBEDTLS_X509_CHECK_EXTENDED_KEY_USAGE
#define MBEDTLS_X509_RSASSA_PSS_SUPPORT

/* PEM CA certificates */
#define MBEDTLS_BASE64_C
#define MBEDTLS_PEM_PARSE_C

/* Required by curl for CA files and TLS sockets */
#define MBEDTLS_NET_C

/*
 * Keep only the TLS cipher suites required for the selected
 * ECDHE-RSA / ECDHE-ECDSA + AES-GCM configuration.
 */
#define MBEDTLS_SSL_CIPHERSUITES                                      \
    MBEDTLS_TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,                   \
    MBEDTLS_TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,                   \
    MBEDTLS_TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,                 \
    MBEDTLS_TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384

/*
 * Reduce ECC RAM usage. 384-bit curves require 48-byte MPI values.
 */
#define MBEDTLS_MPI_MAX_SIZE 48
#define MBEDTLS_ECP_WINDOW_SIZE 2
#define MBEDTLS_ECP_FIXED_POINT_OPTIM 0

/*
 * The default is larger than required for this configuration.
 * Two sources leave room for the platform entropy source.
 */
#define MBEDTLS_ENTROPY_MAX_SOURCES 2

#include "mbedtls/check_config.h"

#endif /* MBEDTLS_CONFIG_H */
