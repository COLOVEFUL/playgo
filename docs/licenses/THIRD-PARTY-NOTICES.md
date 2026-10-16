# Third-Party Notices

PlayGo 自身代码以 MIT 许可发布（见仓库根 LICENSE）。以下为 PlayGo 依赖或分发的
第三方组件及其许可证。PlayGo's own code is MIT-licensed (see LICENSE).

## 分发的组件（打包进发行版 / 按需下载）

| 组件 | 用途 | 许可证 | 文本 |
|---|---|---|---|
| [KataGo](https://github.com/lightvector/KataGo) v1.18.1（OpenCL / Eigen 官方发行 exe） | 围棋 AI 引擎，作为独立子进程调用（不链接其代码） | MIT | `KATAGO-ENGINE-LICENSE.txt` |
| [kata1-b18c384nbt](https://katagotraining.org/networks/) 神经网络 | 引擎权重，来自 katagotraining.org 官方发布 | KataGo Neural Network License（MIT 式） | `KATAGO-NETWORK-LICENSE.txt` |

说明：KataGo 发行 zip 内已包含其自身第三方库（clblast、half、nlohmann_json 等）
的许可文件，随发行包原样分发即满足要求。引擎与模型不入 git 仓库，首次使用时
从官方源下载到本地 `backend/engines/`。

## Python 运行时依赖（backend，随 uv 安装）

| 组件 | 许可证 |
|---|---|
| FastAPI / Starlette | MIT |
| Pydantic | MIT |
| uvicorn | BSD-3-Clause |
| （完整传递依赖清单见 `backend/uv.lock`） | 多为 MIT/BSD/Apache 类宽松许可 |

## 前端构建工具链（仅构建期使用，不随发行版分发）

| 组件 | 许可证 |
|---|---|
| Vite | MIT |
| TypeScript | Apache-2.0 |

发行包中的前端产物（`frontend/dist/`）为 PlayGo 自身源码编译输出，不含上述库的代码。

## 其他

- 音效由 WebAudio 实时合成，未打包任何音频资源
- 字体使用操作系统自带字体栈（KaiTi / SimSun / Microsoft YaHei / Georgia 等），未分发字体文件
