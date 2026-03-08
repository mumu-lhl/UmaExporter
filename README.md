# UmaExporter

另一个 UMA 导出器，可以直接预览并导出场景，以及快速查看贴图。

## 安装

需要预先安装 [.Net 9 运行时](https://dotnet.microsoft.com/zh-cn/download/dotnet/9.0)。

可以到本项目的 GitHub Action 中找安装包，每次提交都会自动生成安装包。

或者在 Release 中下载。

## 版本介绍

* **pyinstaller** : 由 pyinstaller 打包，速度偏慢
* **nuitka** : 由 nuitka 打包，速度快，可能有稳定性问题

## 使用说明

* nuitka 打包版本切记目录中不能包含中文
* Animator、Mesh、Texture2D、Sprite 可以点击预览

对象类型：

* Animator 通常是完整的场景
* Mesh 白模
* Texture2D 和 Sprite 都是贴图
