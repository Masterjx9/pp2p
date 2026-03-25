#pragma once

#include <string>

namespace p4 {

void set_library_path(const std::string &path);
std::string resolve_library_path();
void set_onionrelay_path(const std::string &path);
std::string resolve_onionrelay_path();
std::string generate_identity_json();
std::string peer_id_from_public_key_b64(const std::string &public_key_b64);

}  // namespace p4
