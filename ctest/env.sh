#!/bin/bash
# 手工 MSVC x64 环境。
#
# 为什么不用 vcvars64.bat：它依赖 reg.exe，被本机安全策略拦掉（见 build_llama.bat
# 里同样的注释）。所以 PATH/INCLUDE/LIB 只能自己拼。
#
# 这里**不写任何版本号**。2022 -> 2026 升级、或干脆卸掉旧版，这个文件都不用改。
# 解析顺序：
#   1. $MSVC_VER / $SDK_VER 显式指定（做 A/B 时用，例：MSVC_VER=14.44 source env.sh）
#   2. 枚举 C:/Program Files/Microsoft Visual Studio/<2022 或 18>/<版本>/VC/Tools/MSVC/14.*
#      取版本号最大的一套。"2022" 和 "18" 两种目录命名都覆盖（VS 2026 用 18）
#   3. SDK 从 C:/Program Files (x86)/Windows Kits/10/Include/10.0.* 取最大
#
# 用法：source ctest/env.sh
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
WSDK="/c/Program Files (x86)/Windows Kits/10"             # 这个根目录跨 VS 版本不变

_w() { cygpath -w "$1"; }    # unix -> C:\...（带空格也不用管）
_m() { cygpath -m "$1"; }    # unix -> C:/...（给 CMake 用）

# 所有已安装的 MSVC 工具集，一行一个
_msvc_dirs() {
    local d
    for d in "/c/Program Files/Microsoft Visual Studio"/*/*/VC/Tools/MSVC/14.*; do
        [ -d "$d" ] && printf '%s\n' "$d"
    done
}

_pick_msvc() {
    local d hit=""
    if [ -n "${MSVC_VER:-}" ]; then
        while IFS= read -r d; do
            case "$(basename "$d")" in
                "$MSVC_VER"*) hit="$d" ;;
            esac
        done < <(_msvc_dirs | sort -V)
        if [ -z "$hit" ]; then
            echo "env.sh: MSVC_VER=$MSVC_VER 没找到。已装的有：" >&2
            _msvc_dirs | sed 's#.*/##' >&2
            return 1
        fi
        printf '%s' "$hit"
    else
        _msvc_dirs | sort -V | tail -1
    fi
}

_pick_sdk() {
    if [ -n "${SDK_VER:-}" ]; then
        printf '%s' "$SDK_VER"
        return 0
    fi
    ls -d "$WSDK/Include/10.0."* 2>/dev/null | sed 's#.*/##' | sort -V | tail -1
}

MSVC="$(_pick_msvc)" || { echo "env.sh: 找不到 MSVC 工具集，先装 VS 的「桌面 C++ 开发」工作负载。" >&2; return 1 2>/dev/null || exit 1; }
SDKV="$(_pick_sdk)"
if [ -z "$SDKV" ]; then
    echo "env.sh: 找不到 Windows SDK（$WSDK/Include/10.0.*）。" >&2
    return 1 2>/dev/null || exit 1
fi

export MSVC WSDK SDKV
export PATH="$MSVC/bin/Hostx64/x64:$WSDK/bin/$SDKV/x64:$ROOT/.venv/Scripts:$PATH"
export INCLUDE="$(_w "$MSVC/include");$(_w "$WSDK/Include/$SDKV/ucrt");$(_w "$WSDK/Include/$SDKV/um");$(_w "$WSDK/Include/$SDKV/shared");$(_w "$WSDK/Include/$SDKV/winrt");$(_w "$WSDK/Include/$SDKV/cppwinrt")"
export LIB="$(_w "$MSVC/lib/x64");$(_w "$WSDK/Lib/$SDKV/um/x64");$(_w "$WSDK/Lib/$SDKV/ucrt/x64")"
# 注意：不要给 cmake 传 -DCMAKE_MT / -DCMAKE_RC_COMPILER。
# SDK 的 bin 已经在 PATH 上，cmake 自己找得到；而传进去会因为路径里的
# "C:\Program Files" 里的 \P 被当成转义序列，报 Invalid character escape '\P'。
export CMAKE_MT="$(_m "$WSDK/bin/$SDKV/x64/mt.exe")"
export RC="$(_m "$WSDK/bin/$SDKV/x64/rc.exe")"
