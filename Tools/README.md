# Tools：内容构建与编辑器自动化脚本

`L_Pampas` 的资产、材质、PCG 和关卡 Actor 全部由这些脚本生成或修改，可以重复运行。脚本按作者本机目录编写：研究目录 `D:/HOU/Ghost of Tsushima`，UE 工程 `D:/UE_Project/GhostOfTsushima_`，引擎 `D:/UE/UE_5.8`。在别的机器上使用前，请先改脚本顶部的 `ROOT` 等路径常量。

部分脚本会读取本地研究数据，这些数据**不随仓库分发**：

- 截帧得到的草种表 `Captures/analysis/shaders_02/res3558_kinds.bin`；
- 从游戏资源转换出的芒草图集和枫树网格，位于 `Extracted/`。

所以这里的脚本主要用于说明场景是怎么搭起来的，不能离开这些数据单独复现。

## 运行方式

| 方式 | 用法 | 说明 |
|---|---|---|
| 在打开的编辑器里远程执行 | `python -I Tools/mcp/ue_py.py <script.py>` | 需要在项目设置里开启 Python Remote Execution（仅本机）。脚本里可以直接用 `unreal` 模块，`print` 的输出会传回终端 |
| 完整编辑器启动执行 | `powershell -File Tools/run_ue_script.ps1 <script> <log>` | 以 `-ExecutePythonScript` 启动编辑器，脚本跑完自己退出。用于需要整图生成的步骤 |
| Blender | `blender -b --python-exit-code 1 -P <script.py>` | 生成芒草网格和 LOD |
| 独立 Python | `python -I <script.py>` | 生成高度图、草种图等数据贴图 |

## 脚本索引（大致按搭建顺序）

**地形与地图骨架**

- `build_pampas_v2_heightmap.py`：生成 1009×1009 的 16 位高度图。中央是草原台地，东侧是海崖，南侧是山脊。
- `ue_pampas_v2_setup.py`：新建 World Partition 地图 `L_Pampas`，放出生点和参考相机，生成按坡度和高度自动混合的地形材质。
- `ue_pampas_editor_autoload.py`：放置覆盖全图的 `LocationVolume`，并验证重新打开地图后编辑器能直接看到全部分块。配合 `Content/Python/init_unreal.py` 使用。

**芒草与 PCG**

- `build_pampas_v2_assets.py`：在 Blender 里用芒草图集卡片搭芒草丛，显式生成 4 级 LOD。依赖 `build_m1_geometry.py` 和 `blender_asset_preview.py` 里的网格辅助函数。
- `ue_pampas_v2_vegetation.py`：导入贴图和网格，创建芒草材质，生成分区 PCG。
- `ue_pampas_lod_fade.py`：处理跑图时的 LOD 跳变。LOD 距离推远，开启 Dithered LOD Transition，剔除改为抖动溶解。
- `ue_pampas_far_field.py`：把远层芒草的剔除距离拉到 1 km，图集开启 alpha coverage 保持，并修正地形远景色。
- `ue_expose_pampas_pbr.py`：把芒草材质的着色常量改成参数，生成 `MI_PampasFoliage`。

**枫树与大世界**

- `ue_pampas_trees_uniform.py`：5×5 分块的空间加载 PCG，分层抖动撒点，射线落到地形，过滤陡坡，生成 Nanite 实例，远处交给 HLOD。
- `ue_pampas_tree_check.py`：设置 Nanite Preserve Area，并用水平射线验证树干碰撞。
- `ue_wind_trees_wpo.py`：120 m 外的树停止 WPO。Nanite 植被动起来时 VSM 每帧都要重绘对应页面，远处的树几乎看不出动静。
- `ue_build_hlod.sh`：用 `WorldPartitionBuilderCommandlet` 构建 HLOD。

**GPU 草与统一风场**

- `build_grass_maps.py`：生成 GPU 草的草种图和草高图，网格与高度图一致。
- `ue_grass_setup.py`：GPU 草和风场相关的全部内容，包括：
  - 数据贴图；
  - `MPC_Wind`；
  - `RT_GoTInteraction`（256² RGBA16F，开启 UAV）；
  - `MF_GoTWind`、`MF_GoTWindDebug`，以及调用它们的材质的重新连线；
  - `M_GoTGrass`（Substrate，双面）；
  - 草 Actor `Pampas_GPUGrass`。
- `ue_pcg_remove_blades.py`：GPU 草上线后，删除 PCG 里旧的草叶卡片层。
- `ue_apply_wind_system.py`、`ue_apply_wind_revision.py`：风场的两次增量改版。新增细节噪声层，两层分别设置传播速度，芒草改为圆弧弯曲，同时更新风材质函数和控制器参数。
- `ue_apply_grass_clumping.py`、`ue_expose_grass_pbr.py`：草簇法线和中景草簇参数，以及草材质的 PBR 参数化。

**编辑器自动化**

- `mcp/ue_py.py`：通过 PythonScriptPlugin 的远程执行协议，在打开的编辑器里运行脚本。
- `mcp/pie_start.py`、`mcp/pie_probe.py`、`mcp/pie_stop.py`：启动 PIE，读取叶数和角色处的风力，再停止 PIE。
- `mcp/ue_save_quit.py`：编译 C++ 前保存并关闭编辑器。
- `mcp/ue_editor_open_pampas.py`：重新打开 `L_Pampas`。
- `run_ue_script.ps1`：以完整编辑器启动方式执行一个脚本。

没有收录的内容：
- 截帧分析工具、解包工具；
- 早期路线的脚本（M1 静态场景、`L_PampasDemo`）；
- 一次性探针和验证脚本：依赖本地截帧和备份，在仓库里跑不起来；
- 氛围脚本：当前场景的天空、雾和曝光是之后在编辑器里手动调的，旧脚本已不代表现状。
