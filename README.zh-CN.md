# Uma Exporter

[English](README.md) | 简体中文

Uma Exporter 是一个面向 *赛马娘 Pretty Derby（Uma Musume Pretty Derby）* 游戏数据的桌面工具，用于浏览、检查、预览和导出资源。它结合了 Dear PyGui 提供的响应式界面、UnityPy 的 Unity 资源解析能力，以及外部 CLI / 3D 预览工具来处理更复杂的模型与动画资源。

## 项目亮点

- 基于游戏 `meta` 数据库的高速资源搜索
- 逻辑路径浏览与物理哈希定位
- 检查贴图、网格、动画器等 Unity 内部对象
- 应用内实时贴图预览
- 通过 `f3d` 进行外部 3D 预览
- 支持正向依赖与反向依赖导航
- 支持贴图、文本、音频、网格、动画相关资源导出
- 支持英文和中文界面
- 支持加密与未加密数据库 / 资源包

## 技术栈

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) 用于环境和依赖管理
- [Dear PyGui](https://github.com/hoffstadt/DearPyGui) 用于桌面 UI
- [UnityPy](https://github.com/K00L4ID/UnityPy) 用于 Unity 资源解析
- [f3d](https://f3d.app/) 用于外部 3D 预览
- `as_cli/` 中的 AssetStudioModCLI 二进制用于复杂导出
- 通过 `sqlite3` 与 `apsw-sqlite3mc` 访问 SQLite / SQLite3MC 数据库

## 功能说明

### 资源浏览

- 按逻辑资源路径搜索
- 在场景视图和道具视图中浏览资源
- 使用前进 / 后退历史在资产之间跳转

### 资源检查

- 查看逻辑路径、存储哈希、文件大小和物理位置
- 列出一个 bundle 内包含的 Unity 内部对象
- 双向查看依赖关系

### 资源预览

- 直接在应用内预览 `Texture2D`
- 导出临时 mesh / FBX 数据并交给独立 `f3d` 进程预览
- 支持拖拽悬停式快速检查流程

### 资源导出

- 导出常见 Unity 对象，如贴图、文本资源、音频和网格
- 需要时调用 AssetStudioModCLI 处理动画器 / 模型相关导出
- 支持结合依赖上下文导出复杂资源

## 运行要求

在运行程序前，请确认已经具备：

- Python `3.14` 或更新版本
- 已安装 `uv`
- 一个有效的 *赛马娘* 数据目录，且其中同时包含 `meta/` 和 `dat/`
- `as_cli/` 目录下已放置 AssetStudioModCLI

仓库当前默认使用如下路径形式的 CLI 文件：

- `as_cli/AssetStudioModCLI`
- `as_cli/` 中与之配套的原生动态库

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 启动程序

```bash
uv run main.py
```

### 3. 配置游戏数据路径

首次启动后，请打开 **Settings** 标签页，设置包含以下目录的数据根路径：

- `meta`
- `dat`

随后选择数据区域：

- `jp`
- `global`

应用设置后，程序会重新加载数据库。

## 配置文件

程序会将运行配置写入 `config.json`。

典型内容如下：

```json
{
  "base_path": "/path/to/umamusume/data",
  "language": "Auto",
  "region": "jp"
}
```

说明：

- `base_path` 必须指向同时包含 `meta/` 与 `dat/` 的目录
- `language` 支持 `Auto`、`English`、`Chinese`
- `region` 支持 `jp`、`global`

## 项目结构

```text
.
├── main.py
├── as_cli/
├── src/
│   ├── constants.py
│   ├── database.py
│   ├── decryptor.py
│   ├── unity_logic.py
│   └── ui/
│       ├── i18n.py
│       ├── main_window.py
│       └── controllers/
├── pyproject.toml
└── config.json
```

## 架构概览

### UI 层

`src/ui/main_window.py` 中的 `UmaExporterApp` 是 Dear PyGui 主控制器，负责：

- 应用事件循环
- 导航状态和选择状态
- 通过 `ThreadPoolExecutor` 处理后台任务
- 通过任务队列把 UI 更新安全地切回主线程
- 管理外部 `f3d` 预览进程

### 数据层

`src/database.py` 中的 `UmaDatabase` 负责：

- 以只读方式打开游戏 `meta` 数据库
- 在需要时回退到加密数据库连接方式
- 构建内存中的正向 / 反向依赖图
- 解析 bundle 哈希与解密 key

### Unity / 导出层

`src/unity_logic.py` 负责：

- 加载并解密 bundle
- 提取 Unity 对象元数据
- 生成贴图预览所需数据
- 导出 mesh 与 animator 相关资源
- 将复杂导出委托给 AssetStudioModCLI

## 开发说明

- 不要在后台线程中直接修改 Dear PyGui 控件
- 应通过任务队列把 UI 更新交给主线程执行
- 退出应用时应清理 `f3d` 预览进程
- UI 显示优先使用逻辑名称，数据操作优先使用物理哈希

## 打包相关

仓库中已经包含一些打包相关文件：

- `UmaExporter.spec`
- `setup.py`
- `justfile`

这些文件可以用于本地打包流程；开发阶段的主要运行方式仍然是通过 `uv` 直接启动。

## 常见问题

### 数据库未就绪

请确认配置的数据路径下同时存在 `meta/` 和 `dat/`。

### 没有发现 Unity 对象

有些条目对应的 bundle 可能尚未下载到本地，或者当前无法正确解密。

### 3D 预览无法打开

请检查：

- 环境中的 `f3d` 是否可用
- `as_cli/` 下的 AssetStudioModCLI 及其依赖是否具有可执行权限
- 当前选中的资源是否确实包含 mesh 或 animator 数据

## 免责声明

本项目是第三方资源检查 / 导出工具。请确保你的使用方式符合当地法律法规、平台规则以及游戏服务条款。
