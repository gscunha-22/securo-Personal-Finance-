import { defineConfig } from "@neon/config/v1";

// Neon IaC for preview/CI branches. This file must not declare Functions:
// the ledger API is FastAPI + Celery on persistent compute, not a Neon
// Function. The project is in us-east-2 (Functions-capable) and
// list_functions on main is empty — keep it that way. Long work stays on
// Render/Celery; an SSE/MCP sidecar would be a later addition, never the
// book. `neon checkout` of a new child branch applies the cheap compute
// profile below; the default `main` branch is left untouched.
export default defineConfig({
  branch: (branch) => {
    if (branch.exists || branch.isDefault) return {};
    return {
      ttl: "7d",
      postgres: {
        computeSettings: {
          autoscalingLimitMinCu: 0.25,
          autoscalingLimitMaxCu: 1,
          suspendTimeout: "5m",
        },
      },
    };
  },
});
