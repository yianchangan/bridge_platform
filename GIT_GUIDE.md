# Git 使用指南 — 你的项目场景

## 一、Git 是什么、解决什么问题

没有 Git 时，你修改代码：

```
方案数据库平台_v1.py
方案数据库平台_v2.py
方案数据库平台_v2_最终版.py
方案数据库平台_v2_真的最终版.py
```

有了 Git 之后，**只有一个文件**，每次改动都生成一个"快照"（commit），可以随时回到任何一个历史版本。

**三个核心概念：**

| 概念 | 白话解释 |
|------|---------|
| 工作区 | 你正在编辑的文件，实际存在于硬盘上 |
| 暂存区 | `git add` 之后，标记了"这些文件准备纳入下次快照" |
| 仓库 | `git commit` 之后，快照永久保存在 `.git` 文件夹里 |

你本地的 `.git` 文件夹就是你的**本地仓库**。

---

## 二、本地的 Git 能干什么

在你的 Windows 开发机上，Git 可以**完全独立工作，不需要任何服务器**：

```bash
# 初始化 —— 告诉 Git "开始追踪这个项目"
git init

# 改完代码后
git add .                          # 把改动加入暂存区
git commit -m "修复了XX bug"        # 生成快照

# 查看历史
git log                            # 看所有快照
git diff                           # 看当前改了啥还没暂存

# 回退
git checkout -- 文件名              # 丢弃单个文件的改动
git reset --hard abc123            # 回到某个历史快照
```

这些操作完全在本地完成，不依赖任何网络。

---

## 三、远程仓库是什么

**远程仓库 = 另一台机器上的 `.git` 文件夹副本。**

它的作用只有一个：**作为中心节点，让多台机器之间同步代码**。

你有两个远程仓库：

| 名称 | 地址 | 用途 |
|------|------|------|
| `origin` | GitHub | 代码备份/托管 |
| `server` | 10.84.12.74 | 部署到服务器 |

`origin` 只是 Git 给第一个远程仓库的默认名字，可以叫任何名字。`server` 是你自定义的名字。

---

## 四、两种远程仓库的实际操作

### 4.1 在线仓库（GitHub）

你已经在用了。你去 GitHub 网站创建了一个空仓库，然后：

```bash
# 本地绑定远程地址
git remote add origin https://github.com/yianchangan/bridge_platform

# 把本地的快照推上去
git push -u origin master
```

之后每次改完：
```bash
git add .
git commit -m "描述"
git push origin master
```

**GitHub 的本质**：一台公网的 Git 服务器 + 一个好看的 Web 界面。

---

### 4.2 服务器做远程仓库（你已经建好了）

服务器上执行 `git init --bare` 创建的 `/data/git/bridge_platform.git`，就是一个**裸仓库**。

**裸仓库** = 一个纯粹的 `.git` 内容，没有工作区的文件。它不写代码，只负责接收和存储快照。你不在这个目录里编辑文件。

它的作用就是当"中转站"——你本地推送过去，服务器再从它拉取。

```bash
# 服务器上你已经执行过了
cd /data/git
git init --bare bridge_platform.git
```

本地添加它为远程：
```bash
git remote add server user@10.84.12.74:/data/git/bridge_platform.git
git push -u server master
```

服务器上用它部署：
```bash
cd /data
git clone /data/git/bridge_platform.git bridge_platform
```

---

### 4.3 完整的部署流程

```
你的 Windows 电脑                      服务器 10.84.12.74
─────────────────                      ──────────────────
                        git push
bridge_platform/  ─────────────────→  /data/git/bridge_platform.git
  (工作目录)                           (裸仓库，中转站)

                                       git pull
                                      ←────────
                                      /data/bridge_platform/
                                        (工作目录，运行服务)
```

**每次更新只做两步：**

```bash
# 你的 Windows 电脑
git add .
git commit -m "修复XXX"
git push server master

# SSH 到服务器
ssh user@10.84.12.74
cd /data/bridge_platform
git pull
# 重启服务
```

---

## 五、`git push` / `git pull` 做什么

### push — 把你的推上去

```
你的本地 master 有快照:  A → B → C → D
远程 server/master:      A → B → C

git push server master:  把 D 传给远程，远程也变成 A → B → C → D
```

### pull — 从远程拉下来

```
远程 server/master:  A → B → C → D → E
你的本地 master:     A → B → C → D

git pull:  把 E 拉下来，本地也变成 A → B → C → D → E
```

**push = 把你的给别人，pull = 把别人的给自己。**

---

## 六、分支（branch）是什么

分支就是**一条独立的开发线**。你现在的所有代码都在 `master` 分支上。

### 为什么需要分支

假设前端要你给 API 新加一个字段，但你同时也在改解析器。如果都在 master 上改，代码混在一起，出问题不好隔离。

```bash
# 开个新分支专门加字段
git checkout -b feat/new-field

# 在这个分支上开发、提交
git add .
git commit -m "API 新增审核状态字段"

# 前端测试通过后，把改动合并回 master
git checkout master
git merge feat/new-field

# 删除已用完的分支
git branch -d feat/new-field
```

### 你的场景

目前只有你一个人开发，分支不是必须的。**可以先用 master 推进，等前端加入协作后再用分支隔离。**

---

## 七、你当前的状态总结

```
你本地 bridge_platform/  (master)
       │
       ├── git push ──→  origin (GitHub)
       │
       └── git push ──→  server (10.84.12.74 裸仓库)
                               │
                               └── git pull ──→  /data/bridge_platform/ (运行的服务)
```

你有两个远程，各司其职：GitHub 存档备份，服务器部署运行。

---

## 八、日常命令速查

```bash
# 看看改了什么
git status
git diff

# 保存改动
git add .
git commit -m "描述"

# 推送到所有远程（-a = all）
git push -a

# 或者分别推
git push origin master
git push server master

# 看历史
git log --oneline

# 服务器上更新
git pull

# 丢给远端前确认一下
git status        # 看看有没有忘提交的
```

---

## 九、你现在要做的

1. **本地添加 server 远程**：
   ```bash
   git remote add server user@10.84.12.74:/data/git/bridge_platform.git
   git push -u server master
   ```

2. **服务器上克隆工作目录**：
   ```bash
   ssh user@10.84.12.74
   cd /data
   git clone /data/git/bridge_platform.git bridge_platform
   ```

3. **服务器上运行服务**（在 bridge_platform 工作目录里）：
   ```bash
   cd /data/bridge_platform
   pip install -r requirements.txt
   sudo apt install libreoffice
   nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
   ```
