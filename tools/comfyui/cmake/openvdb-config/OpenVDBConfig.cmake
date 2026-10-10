# WTiVo の wtivo_vdb を、Ubuntu 24.04 の libopenvdb-dev（OpenVDB 10.0.1）でビルドするための最小の設定。
# scripts/build-wtivo.sh が -DOpenVDB_DIR=<このフォルダ> で渡す。
#
# なぜ要るか:
#   WTiVo の CMakeLists.txt は find_package(OpenVDB CONFIG QUIET) を先に試し、無ければ FindOpenVDB.cmake に落ちる。
#   Ubuntu の FindOpenVDB.cmake（/usr/lib/x86_64-linux-gnu/cmake/OpenVDB/FindOpenVDB.cmake:504）は
#   find_package(Boost REQUIRED COMPONENTS iostreams) を無条件に呼ぶが、その cmake 設定を持つ
#   libboost-iostreams-dev は libopenvdb-dev の依存に入っておらず、2026-10-02 の時点で未導入だった。
#   OpenVDB の公開ヘッダ（/usr/include/openvdb）は boost/iostreams を含まず、libopenvdb.so 自身が
#   libboost_iostreams.so.1.83.0 にリンクしている（readelf -d で確認）ので、iostreams の開発用ファイルは要らない。
#
# 作るのは FindOpenVDB.cmake と同じ名前の imported target（OpenVDB::openvdb）だけ。
# 付ける定義も FindOpenVDB.cmake と同じく、ABI 版（version.h の OPENVDB_ABI_VERSION_NUMBER）と
# 遅延読み込み（OPENVDB_USE_DELAYED_LOADING）。公開依存は TBB と Imath（Types.h が <Imath/half.h> を読む）。

if(NOT TARGET OpenVDB::openvdb)
  find_package(TBB CONFIG REQUIRED)
  find_package(Imath CONFIG REQUIRED)
  find_package(Threads REQUIRED)

  find_path(OPENVDB_SHIM_INCLUDE_DIR openvdb/version.h REQUIRED)
  find_library(OPENVDB_SHIM_LIBRARY NAMES openvdb REQUIRED)

  file(STRINGS "${OPENVDB_SHIM_INCLUDE_DIR}/openvdb/version.h" _openvdb_shim_abi_line
    REGEX "^#define OPENVDB_ABI_VERSION_NUMBER [0-9]+")
  string(REGEX REPLACE ".* ([0-9]+)$" "\\1" OpenVDB_ABI "${_openvdb_shim_abi_line}")
  file(STRINGS "${OPENVDB_SHIM_INCLUDE_DIR}/openvdb/version.h" _openvdb_shim_version_line
    REGEX "^#define OPENVDB_LIBRARY_(MAJOR|MINOR|PATCH)_VERSION_NUMBER [0-9]+")
  set(_openvdb_shim_version_parts "")
  foreach(_openvdb_shim_line IN LISTS _openvdb_shim_version_line)
    string(REGEX REPLACE ".* ([0-9]+)$" "\\1" _openvdb_shim_number "${_openvdb_shim_line}")
    list(APPEND _openvdb_shim_version_parts "${_openvdb_shim_number}")
  endforeach()
  list(JOIN _openvdb_shim_version_parts "." OpenVDB_VERSION)

  if(NOT OpenVDB_ABI)
    message(FATAL_ERROR "OpenVDB の ABI 版を ${OPENVDB_SHIM_INCLUDE_DIR}/openvdb/version.h から読めません")
  endif()

  add_library(OpenVDB::openvdb SHARED IMPORTED)
  set_target_properties(OpenVDB::openvdb PROPERTIES
    IMPORTED_LOCATION "${OPENVDB_SHIM_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${OPENVDB_SHIM_INCLUDE_DIR}"
    INTERFACE_COMPILE_DEFINITIONS "OPENVDB_ABI_VERSION_NUMBER=${OpenVDB_ABI};OPENVDB_USE_DELAYED_LOADING"
    INTERFACE_LINK_LIBRARIES "TBB::tbb;Imath::Imath;Threads::Threads"
  )
  message(STATUS "OpenVDB（localai の最小設定）: ${OPENVDB_SHIM_LIBRARY} 版 ${OpenVDB_VERSION} ABI ${OpenVDB_ABI}")
endif()

set(OpenVDB_FOUND TRUE)
