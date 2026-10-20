// TEST-ONLY shim: declares the handful of real OpenSSL EVP prototypes used by
// image_organizer.cpp so it can be linked against the system libcrypto.so.3
// when the OpenSSL development headers are not installed. NOT for production:
// install libssl-dev and use the real <openssl/evp.h> instead.
#pragma once
#include <cstddef>
extern "C" {
typedef struct evp_md_ctx_st EVP_MD_CTX;
typedef struct evp_md_st EVP_MD;
#define EVP_MAX_MD_SIZE 64
EVP_MD_CTX* EVP_MD_CTX_new(void);
void EVP_MD_CTX_free(EVP_MD_CTX*);
const EVP_MD* EVP_sha256(void);
int EVP_DigestInit_ex(EVP_MD_CTX*, const EVP_MD*, void* engine);
int EVP_DigestUpdate(EVP_MD_CTX*, const void*, size_t);
int EVP_DigestFinal_ex(EVP_MD_CTX*, unsigned char*, unsigned int*);
}
