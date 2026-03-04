# Information for VPC Endpoint (Other Repo) Team: CloudWatch Logs + ECS Task Failure

DataHub ECS tasks (including one-off migrations) fail with:

```
ResourceInitializationError: failed to validate logger args: The task cannot find the Amazon CloudWatch log group defined in the task definition. There is a connection issue between the task and Amazon CloudWatch. Check your network configuration. : signal: killed
```

Our Terraform and AWS setup on the DataHub side has been verified (log group exists, task definition correct, IAM has logs permissions, subnets and security group aligned). The failure persists **even with assignPublicIp=ENABLED**, so the issue is likely the **private path to the CloudWatch Logs interface endpoint** (or Fargate + private DNS), not log group name or IAM.

---

## Quick reference: exact IDs (DataHub side)

| Item | Value |
|------|--------|
| **VPC** | `vpc-0cc90c92d7897066e` |
| **Task subnets** | Same 4 as endpoint subnets (see below) |
| **Task SG** | `sg-0d53d6ae130b321b5` |
| **Logs endpoint** | `vpce-0c2ab832318d8227d` |
| **Endpoint SG** | `sg-0111d873c5c28caa8` |

**Already verified (no need to re-check):** Endpoint SG allows 443 from task SG; same VPC and subnets; VPC DNS settings and NACLs (no block on 443).

**Still to verify:** Private DNS on the logs endpoint; endpoint in those 4 subnets with that SG; no custom endpoint policy; route table has local route for VPC CIDR; optional: resolve and curl from inside the VPC.

---

## 1. DataHub context (our side)

| Item | Value |
|------|--------|
| **VPC** | `vpc-0cc90c92d7897066e` |
| **Subnets where ECS tasks run** | `subnet-0be9be5b206beac4a`, `subnet-0d62ea769dd7f83dd`, `subnet-0d62a36245dbaa5f4`, `subnet-034768278985bf8e1` |
| **Security group on the task** | `sg-0d53d6ae130b321b5` (DataHub ECS tasks) |
| **CloudWatch Logs endpoint (your side)** | `vpce-0c2ab832318d8227d` (service: `com.amazonaws.us-east-1.logs`) |
| **Endpoint’s security group** | `sg-0111d873c5c28caa8` |

We confirmed:

- Your endpoint SG allows **ingress 443** from `sg-0d53d6ae130b321b5`.
- The four subnets above are the same ones where the CloudWatch Logs endpoint has ENIs.
- VPC has `enableDnsSupport` and `enableDnsHostnames` = true.
- NACLs on the task subnet we checked allow all; no block on 443.

So from our side: task and endpoint are in the same VPC, same subnets, and SG rules allow 443 from our task SG to the endpoint SG.

---

## 2. What we need you to verify (your repo / endpoint)

1. **Private DNS enabled on the Logs endpoint**  
   For the interface endpoint `com.amazonaws.us-east-1.logs` (vpce-0c2ab832318d8227d), confirm **private DNS names** are enabled so that `logs.us-east-1.amazonaws.com` resolves to the endpoint’s private IP(s) inside the VPC.  
   - In Terraform: e.g. `private_dns_enabled = true` on the `aws_vpc_endpoint` for the logs service.  
   - In console: VPC → Endpoints → select the logs endpoint → **Details** → “Private DNS names” = Enabled.

2. **Subnets**  
   Confirm the endpoint is created in exactly these subnets (we already see it in the API):  
   `subnet-0be9be5b206beac4a`, `subnet-0d62ea769dd7f83dd`, `subnet-0d62a36245dbaa5f4`, `subnet-034768278985bf8e1`.  
   No change needed if it’s already so; just confirming.

3. **Security group**  
   Confirm the endpoint uses `sg-0111d873c5c28caa8` and that this SG has **ingress 443** from `sg-0d53d6ae130b321b5` (already verified from our side; double-check on your side if useful).

4. **No restrictive endpoint policy**  
   We see the endpoint policy allows full access. If you have a custom policy, ensure it does not block `logs:CreateLogStream` / `logs:PutLogEvents` (or in practice, any `logs:*` from our account/VPC).

5. **Route tables for the four subnets**  
   Our checks show these four subnets use the VPC **main** route table (no explicit subnet association). With private DNS, traffic to the endpoint’s private IP is covered by the local VPC route (e.g. 172.30.0.0/16 → local). No prefix-list route is required for this interface endpoint. If your Terraform or networking changes the main route table or associations for these subnets, ensure the local route for the VPC CIDR is still present so traffic to the endpoint ENI stays in-VPC.

6. **DNS resolution from inside the VPC**  
   If possible, from a resource in one of the four subnets (e.g. EC2 or a test Fargate task with network tools), run:
   - `nslookup logs.us-east-1.amazonaws.com` or `dig logs.us-east-1.amazonaws.com`  
   and confirm it resolves to a **private IP** in the VPC (e.g. 172.30.x.x).  
   Then test connectivity to that IP on port 443 (e.g. `curl -v https://logs.us-east-1.amazonaws.com` or to the resolved IP).  
   This confirms that private DNS and routing to the endpoint work from the same network path the failing ECS task uses.

7. **Fargate / ECS-specific behavior**  
   If the above checks pass but the ECS task still fails, it may be Fargate-specific (e.g. how the task’s network namespace resolves DNS or uses the endpoint). Any known issues or docs you have for “ECS Fargate + interface endpoint + private DNS” in this VPC would help (e.g. resolver rules, or needing to use a specific subnet/DNS setup).

---

## 3. Useful AWS CLI commands (run in your context)

Run these and confirm the output matches what's expected.

```bash
# 1) Endpoint details: subnets, private DNS, state, SG
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids vpce-0c2ab832318d8227d --region us-east-1 \
  --query 'VpcEndpoints[0].{ServiceName:ServiceName,VpcId:VpcId,SubnetIds:SubnetIds,PrivateDnsEnabled:PrivateDnsEnabled,State:State,Groups:Groups[*].GroupId}'
# Expect: PrivateDnsEnabled=true, State=available, Groups includes sg-0111d873c5c28caa8,
#         SubnetIds = the 4 endpoint subnets (subnet-0be9be5b..., subnet-0d62ea76..., subnet-0d62a362..., subnet-03476827...)

# 2) Endpoint SG: must allow 443 from task SG
aws ec2 describe-security-groups --group-ids sg-0111d873c5c28caa8 --region us-east-1 \
  --query 'SecurityGroups[0].IpPermissions[?ToPort==`443`]'
# Expect: ingress rule with FromPort=443, ToPort=443, UserIdGroupPairs including sg-0d53d6ae130b321b5

# 3) Optional: endpoint policy (default allows full access; custom policy must not block logs:*)
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids vpce-0c2ab832318d8227d --region us-east-1 \
  --query 'VpcEndpoints[0].PolicyDocument'
```

---

## 4. Verification checklist (endpoint-owner side)

Work through in order:

1. **Private DNS** — From the first CLI command, confirm `PrivateDnsEnabled: true`. In this repo the logs endpoint is created with `private_dns_enabled = true` (`terraform/vpc.tf`). If the live endpoint shows `false`, something overrode it (console or another Terraform).

2. **Subnets and SG** — Confirm the endpoint's `SubnetIds` are the four subnets where DataHub runs tasks, and `Groups` includes `sg-0111d873c5c28caa8`. The task SG `sg-0d53d6ae130b321b5` must be allowed ingress 443 on that SG (second CLI command).

3. **Route table** — The route table used by those four subnets (main or explicit association) must have the normal **local** route for the VPC CIDR. No prefix-list route is needed for this interface endpoint.

4. **Optional: prove from inside the VPC** — From an instance or test Fargate task in one of the four subnets: run `nslookup logs.us-east-1.amazonaws.com` or `getent hosts logs.us-east-1.amazonaws.com` (should resolve to a **private** IP in the VPC), then `curl -v --connect-timeout 5 https://logs.us-east-1.amazonaws.com` (should connect; 403/405 is OK; we care about TCP + TLS to the endpoint).

5. **Fargate-specific** — If 1–4 pass but the task still fails, it may be Fargate's resolver or network namespace. Ensure the service uses `awsvpc` network mode and task subnets/SG match the four subnets and `sg-0d53d6ae130b321b5`. Any custom DNS (e.g. Route 53 Resolver rules) in the VPC could affect resolution of `logs.us-east-1.amazonaws.com`.

---

## 5. What we’ve already tried

- Aligning our ECS task subnets with the endpoint subnets (same four as above).
- Running the task with the correct security group (`sg-0d53d6ae130b321b5`).
- Running with **assignPublicIp=ENABLED**; the task still fails with the same error (so the problem appears to be the path to CloudWatch Logs, not a typo in log group name or IAM).
- Running a **diagnostic one-off task** (same subnets, same SG) — it failed with the same `ResourceInitializationError: failed to validate logger args`.

---

## 5b. What to try next (prioritized)

The task cannot reach the CloudWatch Logs API from the Fargate network. The fix is almost certainly on the **VPC endpoint / VPC networking side** (other repo or shared infra).

### 1. VPC endpoint owner: run the Section 3 CLI checks and fix any mismatch

Whoever owns the VPC endpoints (the repo that creates `vpce-0c2ab832318d8227d`) should run:

```bash
export AWS_PROFILE=<their-profile>
# 1) Private DNS must be true; SubnetIds = the 4 subnets; State = available
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids vpce-0c2ab832318d8227d --region us-east-1 \
  --query 'VpcEndpoints[0].{ServiceName:ServiceName,SubnetIds:SubnetIds,PrivateDnsEnabled:PrivateDnsEnabled,State:State,Groups:Groups[*].GroupId}'

# 2) Endpoint SG must allow 443 from sg-0d53d6ae130b321b5
aws ec2 describe-security-groups --group-ids sg-0111d873c5c28caa8 --region us-east-1 \
  --query 'SecurityGroups[0].IpPermissions[?ToPort==`443`]'
```

- If **PrivateDnsEnabled** is **false** → enable private DNS on the logs endpoint so `logs.us-east-1.amazonaws.com` resolves to the endpoint's private IP inside the VPC. Then re-run a DataHub one-off task.
- If **SubnetIds** do not include all four task subnets → add the missing subnets to the endpoint.
- If the endpoint SG does not have an ingress rule for **port 443** from **sg-0d53d6ae130b321b5** → add it and re-run the task.

### 2. VPC endpoint owner: route table for the four subnets

The route table used by subnets `subnet-0be9be5b206beac4a`, `subnet-0d62ea769dd7f83dd`, `subnet-0d62a36245dbaa5f4`, `subnet-034768278985bf8e1` must have the normal **local** route for the VPC CIDR (e.g. `172.30.0.0/16` → local). That way traffic to the endpoint ENI's private IP stays in-VPC. If the main route table was changed or subnets use a custom table that lacks the local route, fix it.

### 3. Check for Route 53 Resolver rules

If the VPC has **Route 53 Resolver** rules (e.g. forwarding `*.amazonaws.com` or specific domains), they can override resolution of `logs.us-east-1.amazonaws.com`. If a rule sends that name to a different DNS or to an unreachable IP, the task will fail. The endpoint owner or VPC admin should review Resolver rules and either ensure `logs.us-east-1.amazonaws.com` resolves to the interface endpoint's private IP(s) or temporarily disable/amend the rule and re-test.

**Confirmed:** We do not have Route 53 Resolver in this VPC; this is not the cause of the failure.

### 4. DataHub side: optional re-test with assignPublicIp=ENABLED

You already tried this and it failed; that often means the task is still resolving `logs.us-east-1.amazonaws.com` to the **private** endpoint IP (via Private DNS or a Resolver rule), and that path is broken. If the endpoint owner has **fixed** Private DNS and SG/routes, run the migration (or diagnostic) task again with the **same** subnets and SG. No need to change assignPublicIp unless you want to test the public path from a subnet that has a NAT Gateway (so the task can reach the internet); then the task would use the public CloudWatch Logs endpoint only if DNS did not resolve to a private IP.

### 5. If the endpoint owner confirms everything is correct

If Private DNS is enabled, endpoint is in the four subnets, SG allows 443 from the task SG, and route tables have the local route, but the task still fails, the remaining possibility is **Fargate-specific** (e.g. resolver or network namespace in this VPC). Escalate to the endpoint/VPC owner with the exact error and ask for any known issues with ECS Fargate + interface endpoints + private DNS, or for a test from an **EC2** instance in the same subnet (nslookup + curl to `logs.us-east-1.amazonaws.com`) to compare behavior.

---

## 6. DataHub side: verify migration task network config (awsvpc, subnets, SG)

Before or after the endpoint checks, confirm the **one-off migration task** is launched with the correct network configuration:

| Requirement | How to verify |
|-------------|----------------|
| **awsvpc** | Task definition `datahub-prod-web` has `networkMode: "awsvpc"` (already set in Terraform). |
| **Subnets** | Run-task must use the **same four subnets** as the logs endpoint. From datahub-infra: `terraform output -json ecs_run_task_subnet_ids` should list exactly: `subnet-0be9be5b206beac4a`, `subnet-0d62ea769dd7f83dd`, `subnet-0d62a36245dbaa5f4`, `subnet-034768278985bf8e1`. |
| **Security group** | Run-task must pass `securityGroups=[sg-0d53d6ae130b321b5]` (i.e. `ecs_run_task_security_group_ids`). |

If you use different subnets or a different SG when running the migration, the task may not be in the same network path as the endpoint. Always run the migration like this (from `datahub-infra/infrastructure/terraform/environments/prod`, using the **terraform-deployer** AWS profile):

```bash
cd infrastructure/terraform/environments/prod
export AWS_PROFILE=terraform-deployer

SUBNETS=$(terraform output -json ecs_run_task_subnet_ids | jq -r 'if type=="array" then join(",") else . end')
SGS=$(terraform output -json ecs_run_task_security_group_ids | jq -r 'if type=="array" then join(",") else . end')
# Confirm before running:
echo "Subnets: $SUBNETS"
echo "Security groups: $SGS"   # should be sg-0d53d6ae130b321b5

aws ecs run-task --cluster datahub-prod-cluster \
  --task-definition datahub-prod-web \
  --overrides '{"containerOverrides":[{"name":"web","command":["python","manage.py","migrate","--noinput"]}]}' \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SGS],assignPublicIp=DISABLED}"
```

**Custom DNS:** If your VPC has Route 53 Resolver rules (e.g. forwarding to on-prem or another DNS), ensure they do not change resolution of `logs.us-east-1.amazonaws.com` so it still resolves to the VPC endpoint's private IP(s).

---

## 7. DataHub side: run diagnostic one-off task (DNS + HTTPS from inside VPC)

If endpoint checks (Section 4) pass but the real migration task still fails with the CloudWatch logger error, run a **diagnostic one-off Fargate task** in the same four subnets with the same SG. Use a small image with `nslookup` and `curl` and **no CloudWatch logging** (so the task can start even when the logs endpoint is unreachable). This proves whether `logs.us-east-1.amazonaws.com` resolves to a private IP and HTTPS connects from the task's network.

### 7.1 Register a minimal task definition (once)

This task definition uses **json-file** logging so the container starts without contacting CloudWatch. From `datahub-infra/infrastructure/terraform/environments/prod`, use the **terraform-deployer** AWS profile, get the execution role, and register the task definition:

```bash
cd infrastructure/terraform/environments/prod
export AWS_PROFILE=terraform-deployer

EXEC_ROLE=$(terraform output -raw ecs_execution_role_arn)
# Or from the web task definition if the output is not available:
# EXEC_ROLE=$(aws ecs describe-task-definition --task-definition datahub-prod-web --query 'taskDefinition.executionRoleArn' --output text)

# Register the diagnostic task definition (sed replaces EXEC_ROLE_ARN with your role ARN)
sed "s|EXEC_ROLE_ARN|$EXEC_ROLE|g" <<'EOF' | aws ecs register-task-definition --region us-east-1 --cli-input-json file:///dev/stdin
{
  "family": "datahub-prod-logs-endpoint-test",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "EXEC_ROLE_ARN",
  "taskRoleArn": "EXEC_ROLE_ARN",
  "containerDefinitions": [{
    "name": "test",
    "image": "public.ecr.aws/docker/library/alpine:latest",
    "logConfiguration": { "logDriver": "json-file" },
    "command": ["sh", "-c", "apk add --no-cache bind-tools curl && nslookup logs.us-east-1.amazonaws.com && curl -v --connect-timeout 5 https://logs.us-east-1.amazonaws.com 2>&1; exit 0"],
    "essential": true
  }]
}
EOF
```

### 7.2 Run the diagnostic task

Use the **same subnets and security group** as the migration task (with **terraform-deployer** profile):

```bash
cd infrastructure/terraform/environments/prod
export AWS_PROFILE=terraform-deployer

SUBNETS=$(terraform output -json ecs_run_task_subnet_ids | jq -r 'if type=="array" then join(",") else . end')
SGS=$(terraform output -json ecs_run_task_security_group_ids | jq -r 'if type=="array" then join(",") else . end')

aws ecs run-task --region us-east-1 --cluster datahub-prod-cluster \
  --task-definition datahub-prod-logs-endpoint-test \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SGS],assignPublicIp=DISABLED}"
```

Note the `taskArn` from the output.

### 7.3 Interpret the result

1. **Task reaches RUNNING and then stops**  
   - If the container exits with code **0**: the commands ran; `nslookup` and `curl` completed. That means from inside the task, `logs.us-east-1.amazonaws.com` resolved and HTTPS connected (e.g. to the private endpoint). In that case the remaining suspect is **Fargate's resolver/network namespace** or **custom DNS** affecting the real migration task (Section 4.5).
   - If the container exits with a **non-zero** code: install or one of the commands failed (e.g. resolution or connection failed).

2. **Task fails in PROVISIONING or never reaches RUNNING**  
   - Check the task's stopped reason. If it's a resource or launch error, fix that first. This diagnostic task does not use CloudWatch logs, so it should not fail with "failed to validate logger args".

3. **Seeing the actual nslookup/curl output**  
   - With `json-file` you don't get logs in CloudWatch. To see output you'd need ECS Exec (SSM) or to change the task to use `awslogs` (then it would only start if the logs endpoint is reachable). The exit code is enough to know whether resolution and HTTPS succeeded.

If the diagnostic task **succeeds** (exit 0) but the **migration task still fails**, the problem is likely Fargate-specific (resolver/network namespace) or a Route 53 Resolver rule affecting `logs.us-east-1.amazonaws.com` for the migration task's context. Share that outcome with the VPC endpoint team and ask about any known ECS Fargate + interface endpoint + private DNS quirks in this VPC.

---

## 8. Contact

If you need more details (e.g. task ID of a failed run, exact timestamp, or a copy of our Terraform for the task definition / IAM), we can provide them. We’re happy to run any further tests from our side (e.g. another task with different options) if you suggest them.
