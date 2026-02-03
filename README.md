# Artifact Live - Multi-Business Operations Platform

[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![React](https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://reactjs.org/)
[![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)

> A portable, multi-business inventory and project management platform with real double-entry accounting, FIFO costing, and business-specific workflows. One core engine, multiple business wrappers.

---

## 📋 Table of Contents

- [About the Project](#-about-the-project)
- [Business Modules](#-business-modules)
- [Core Features](#-core-features)
- [Technical Highlights](#-technical-highlights)
- [Quick Start](#-quick-start)
- [API Documentation](#-api-documentation)
- [Database Schema](#-database-schema)
- [Roadmap](#-roadmap)
- [Related Projects](#-related-projects)
- [License](#-license)

---

## 🎯 About the Project

**Artifact Live** is a full-stack business operations platform designed to run multiple small businesses from a single codebase. Each business gets its own workflow and UI, but shares a battle-tested core: double-entry accounting, FIFO inventory costing, and proper financial tracking.

### Why I Built This

I run multiple side businesses - custom keyboard builds, electronics projects, computer refurbishment. Each has different workflows but the same underlying need: know what inventory I have, what it cost, and whether I'm making money.

Most inventory apps are either too simple (spreadsheets with no accounting) or too complex (enterprise ERP systems). I needed something in between: real accounting principles wrapped in business-specific interfaces.

The solution: build a core engine once, then wrap it for each business type. The keyboard business gets a BOM builder. The computer shop gets a part-out workflow. Same foundation, different faces.

### What It Does

- **Multi-business isolation** - Each business has its own projects, states, and workflows
- **Shared inventory model** - Parts exist in a catalog, allocated to specific projects
- **Real FIFO costing** - Know the actual cost of goods sold, not averages
- **Double-entry accounting** - Every transaction balances, every dollar is tracked
- **Portable deployment** - SQLite database means you can hand someone a folder

### Part of a Larger System

Artifact Live is the third piece of a connected accounting ecosystem:

| Project | Purpose | Status |
|---------|---------|--------|
| [Perfect Books](https://github.com/matthew-s-jenkins/perfect-books) | Personal finance management | In daily use |
| [Digital Harvest](https://github.com/matthew-s-jenkins/digital-harvest-sim) | Business simulation / learning sandbox | Complete |
| **Artifact Live** | Real business operations | Active development |

The progression:
- **Perfect Books** proved the accounting patterns work for real money
- **Digital Harvest** stress-tested inventory + accounting at scale (simulated)
- **Artifact Live** applies both to real business operations

All three share the same core architecture: Flask API, React frontend, SQLite database, double-entry ledger.

---

## 🏢 Business Modules

### ⌨️ Keyboards (Active Development)

**Parts → BOM → Build → Sale**

Track switches, keycaps, PCBs, cases. Build BOMs for custom keyboards. Calculate true cost per build. Track profitability on sales.

| Feature | Status |
|---------|--------|
| Parts catalog with categories | ✅ Complete |
| Quantity tracking with mystery parts | ✅ Complete |
| Project lifecycle (PLANNED → ASSEMBLED → SOLD) | ✅ Complete |
| Part allocation with partial quantities | ✅ Complete |
| Build planning with availability analysis | ✅ Complete |
| Disassembly workflow (return parts to inventory) | ✅ Complete |
| Dashboard with inventory/project overview | ✅ Complete |
| BOM templates | 🔜 Planned |

### 💻 Computer Chop Shop (MVP Complete)

**Acquire System → Part Out → Sell Components**

Buy used systems, part them out, sell components individually. Parent-child inventory structure. Break-even calculator with fee estimation.

| Feature | Status |
|---------|--------|
| Project creation with acquisition cost | ✅ Complete |
| Parts tracking with status workflow | ✅ Complete |
| eBay fee calculator | ✅ Complete |
| Profitability tracking | ✅ Complete |

### ⚡ Electrical Client (Planning)

**Materials → Job Allocation → Job Costing**

External client deployment for family electrical business. Track materials per job. Calculate job profitability. Owner and Technician role separation.

| Feature | Status |
|---------|--------|
| Requirements gathering | 🔜 Next |
| Job-based inventory allocation | 🔜 Planned |
| Role-based access | 🔜 Planned |

---

## ✨ Core Features

### 📦 Inventory Management

- **Parts Catalog** - Reusable catalog entries with categories, default prices, weight classes
- **Quantity Tracking** - Track bulk items (90 switches) not just individual parts
- **Mystery Parts** - Placeholder entries for unidentified parts, identify later
- **Metadata Support** - Flexible JSON fields for switch mods (lubed, filmed, spring-swapped)
- **Availability Breakdown** - See Total | Available | In Projects (For Sale vs Personal)

### 🔧 Project Management

- **Business-Specific Statuses** - CCS: ACQUIRED → PARTING → SOLD, Keyboards: PLANNED → ASSEMBLED → DEPLOYED
- **For Sale Flag** - Distinguish builds for sale vs personal use
- **Part Allocation** - Assign inventory to projects with over-allocation prevention
- **Partial Allocation** - Allocate 67 of 90 switches, leaving 23 in inventory

### 📊 Build Planning

- **Availability Analysis** - See what's available, what needs sourcing, what requires disassembly
- **Disassembly Suggestions** - "Need to disassemble Keyboard X to get Y switches"
- **Staged Mode** - Plan a build without committing parts
- **Confirm/Cancel** - Commit staged parts or return to inventory

### 🔄 Disassembly Workflow

- **Return Parts to Inventory** - Disassemble a build, parts go back to loose inventory
- **Consumables Handling** - Foam, lube, tape marked as destroyed (TRASHED)
- **Mystery Identification** - Identify unknown parts during disassembly

### 📈 Dashboard

- **At-a-Glance View** - Total parts by category, available vs allocated
- **Project Status** - Quick counts by status, recent projects list
- **Quick Filters** - For Sale, Personal, In Progress

---

## 🔧 Technical Highlights

### Architecture

- **API-first design** - Flask REST API with clean separation from frontend
- **Business isolation via subsection_id** - Single database, complete data separation
- **Wrapper pattern** - Core engine handles accounting/inventory, business modules handle workflows

### Accounting Engine

- **Double-entry ledger** - Every transaction creates balanced DR/CR entries
- **FIFO inventory costing** - Accurate COGS calculation, not averages
- **Immutable audit trail** - Transactions are reversed, never deleted
- **Transaction UUIDs** - Group related entries for atomic operations

### Why SQLite

- **Portable** - Entire app is one folder, no database server
- **Distributable** - Can deploy to clients by copying files
- **Scalable path** - PostgreSQL migration ready when concurrent access is needed

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** ([Download](https://www.python.org/downloads/))
- A modern web browser

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/matthew-s-jenkins/artifact-live.git
   cd artifact-live
   ```

2. **Set up the backend**
   ```bash
   cd backend
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # Mac/Linux
   source venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Initialize the database**
   ```bash
   python -c "from database.setup import init_db; init_db()"
   ```

4. **Run the server**
   ```bash
   python app.py
   ```

5. **Open in browser**
   Navigate to `http://localhost:5000`

---

## 📡 API Documentation

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/register` | Create account |
| POST | `/api/login` | Authenticate |
| POST | `/api/logout` | End session |
| GET | `/api/health` | Server status |

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects` | List projects (with filters) |
| POST | `/api/projects` | Create project |
| GET | `/api/projects/<id>` | Get project with parts |
| PUT | `/api/projects/<id>` | Update project |
| DELETE | `/api/projects/<id>` | Delete project |
| POST | `/api/projects/<id>/disassemble` | Disassemble (return parts) |
| POST | `/api/projects/<id>/plan-build` | Analyze part availability |
| POST | `/api/projects/<id>/confirm-staged` | Confirm staged parts |
| POST | `/api/projects/<id>/cancel-staged` | Cancel staged parts |

### Parts & Inventory

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/projects/<id>/parts` | Add part to project |
| GET | `/api/projects/<id>/parts` | List project parts |
| PUT | `/api/parts/<id>` | Update part |
| DELETE | `/api/parts/<id>` | Delete part |
| POST | `/api/inventory` | Create loose inventory |
| GET | `/api/inventory` | List loose inventory |
| GET | `/api/inventory/summary` | Availability breakdown |
| POST | `/api/parts/<id>/allocate` | Allocate to project |
| POST | `/api/parts/<id>/deallocate` | Return to inventory |

### Catalog

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/catalog` | List catalog entries |
| POST | `/api/catalog` | Add catalog entry |
| POST | `/api/catalog/seed-keyboard` | Seed keyboard categories |
| PUT | `/api/catalog/<id>` | Update entry |
| DELETE | `/api/catalog/<id>` | Delete entry |

### Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard` | Inventory & project stats |

---

## 🗄️ Database Schema

### Core Tables

| Table | Purpose |
|-------|---------|
| `users` | Authentication with bcrypt password hashing |
| `subsections` | Business units (Keyboards, CCS, etc.) |
| `projects` | Individual builds/acquisitions |
| `project_parts` | Parts with status, quantity, allocation |
| `parts_catalog` | Reusable part definitions |
| `financial_ledger` | Double-entry accounting (future) |
| `inventory_layers` | FIFO cost tracking (future) |

### Part Status Flow

```
IN_SYSTEM → ALLOCATED → IN_PROJECT → SOLD
    ↓           ↓
  STAGED     TRASHED (consumables)
    ↓
 ALLOCATED (on confirm)
```

### Project Status Flow

**Computer Chop Shop:**
```
ACQUIRED → PARTING → LISTED → SOLD → COMPLETE
```

**Keyboards:**
```
PLANNED → IN_PROGRESS → ASSEMBLED → DEPLOYED → DISASSEMBLED
```

---

## 🗺️ Roadmap

### Stage 1: Personal Use (Current)

Prove the platform works for my own businesses. Daily use for keyboard inventory and builds.

- ✅ Phase 1.0: Foundation - Schema, statuses, bidirectional flow
- ✅ Phase 1.1: Parts Catalog - CRUD, categories, mystery parts
- ✅ Phase 1.2: Project Management - Statuses, for_sale flag
- ✅ Phase 1.3: Part Allocation - Partial quantities, staged mode
- ✅ Phase 1.4: Disassembly Workflow - Return parts, handle consumables
- ✅ Phase 1.5: Build Planning - Availability analysis, disassembly suggestions
- ✅ Phase 1.6: Dashboard - At-a-glance inventory and project status
- 🔜 Phase 2.0: BOM Templates - Save and reuse build configurations
- 🔜 Phase 2.1: Financial Integration - Cost tracking, profitability

### Stage 2: First Client

Deploy to Family Electric. Get real feedback from a real business user.

### Stage 3: Revenue

Monthly hosting/support fee from clients. Recurring revenue from the platform.

### Stage 4: Scale

- PostgreSQL migration for concurrent multi-user access
- Cloud deployment for mobile/field access
- Additional business wrappers as client needs emerge

**The Goal:** Software that runs businesses. Financial independence through recurring revenue from small business clients who need real inventory tracking without enterprise complexity.

---

## 🔗 Related Projects

### Perfect Books - Personal Finance Management

Artifact Live shares its **double-entry accounting foundation** with [Perfect Books](https://github.com/matthew-s-jenkins/perfect-books).

**Shared Principles:**
- ✅ Double-entry accounting (Assets = Liabilities + Equity)
- ✅ Immutable financial ledger with transaction UUIDs
- ✅ SQLite database with full portability
- ✅ Flask REST API architecture
- ✅ React + Tailwind CSS frontend

### Digital Harvest - Business Simulation

[Digital Harvest](https://github.com/matthew-s-jenkins/digital-harvest-sim) stress-tested these patterns at scale before Artifact Live applied them to real operations.

---

## 📜 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 📧 Contact

**Matthew Jenkins**
- GitHub: [@matthew-s-jenkins](https://github.com/matthew-s-jenkins)
- LinkedIn: [linkedin.com/in/matthew-s-jenkins](https://www.linkedin.com/in/matthew-s-jenkins/)

---

**Built with Python, Flask, React, and SQLite**
