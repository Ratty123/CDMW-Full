#pragma once

#if defined(_WIN32) && defined(CDMW_MESH_INTERACTION_ABI_EXPORTS)
#define CDMW_MESH_INTERACTION_API __declspec(dllexport)
#elif defined(_WIN32)
#define CDMW_MESH_INTERACTION_API __declspec(dllimport)
#else
#define CDMW_MESH_INTERACTION_API
#endif
