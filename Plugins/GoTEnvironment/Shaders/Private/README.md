# Shaders/Private

| 文件 | 内容 | 是否公开 |
|---|---|---|
| `GoTWindCommon.ush` | 统一风场公式：3D 改进 Perlin、阵风力、细节层、局部风合成、草叶哈希。GPU 草、草叶 VF 和材质 Custom 节点都 include 这一份 | 公开 |
| `GoTPerlinTables.ush` | Ken Perlin 改进噪声的标准置换表和 32 项梯度表（与截帧常量核对一致） | 公开 |
| `GoTWindField.usf` | 交互场 compute pass：轨迹点阻尼波写 RG，vorticle 局部风写 BA | 公开 |
| `GoTGrassVertexFactory.ush` | 草叶 Vertex Factory：从结构化缓冲读叶片记录，接入 UE 的深度、BasePass 和速度 pass | 公开 |
| `GoTGrassGen.usf` | 草叶生成 `GenerateCS` 与间接参数 `FinalizeCS` | **未公开** |
| `GoTGrassCommon.ush` | 叶片记录布局与逐顶点求值 `GoTEvaluateBlade` | **未公开** |

## 为什么缺两份

这两份是按 PIX 截帧中游戏草叶着色器的反汇编逐步转写的，属于原游戏代码的衍生物，只在本地研究中使用，不随仓库分发。因此仓库里的插件**不能直接编译出可运行的着色器**，它用于阅读 C++ 侧的引擎集成和其余公开着色器。

## 接口（供阅读 C++ 代码时参照）

**`GoTGrassGen.usf`**

- `GenerateCS`：每个 tile 256×256 个线程。参数结构见 `Source/GoTEnvironment/Private/GoTGrassComponent.cpp` 中的 `FGoTGrassGenerateCS::FParameters`：tile 列表、视点与视锥平面、地形高度图、草种图、草高图、草种表、两层风参数（当前帧与上一帧）、交互场纹理。
- 输出：近层和远层两个 `RWStructuredBuffer<float4>`，每片叶 4 个 float4；另有原子计数器、簇法线和逐叶风运动矢量。
- `FinalizeCS`：把近层和远层计数写成两组 `DrawIndexedIndirect` 参数（`FGoTGrassFinalizeCS::FParameters`）。

**`GoTGrassCommon.ush`**

- 叶片记录：
  - `B0` = 相对生成原点的位置 xyz、高度 h；
  - `B1` = 宽度、倾斜、弯曲、草种；
  - `B2` = 朝向 xy、侧向偏移、风值；
  - `B3` = 簇权重、上一帧风值、颜色档位、随机数。
- 常量：近层 15 顶点、每实例 124 片；远层 7 顶点、每实例 136 片。
- `GoTEvaluateBlade(B0..B3, VertexIndex, Lod, Kind, Frame, DispTexture, Sampler)`：求出顶点位置、法线和 UV。`GoTGrassVertexFactory.ush` 分别用当前帧和上一帧的风状态各调用一次，得到运动矢量。

算法的文字说明和伪代码见仓库根目录的 [README](../../../../README.md#gpu-草叶每帧重新生成一遍)。
