# Terraform Ownership and Safe Transfer to Shared Repo

This document explains how the shared networking stack interacts with existing resources and how to safely transfer ownership from acs_processor to this repo **without affecting currently deployed resources**.

---

## Import complete (prod networking)

The **prod** networking stack in this repo has **imported** all shared resources from AWS into state:

- EIP, NAT gateway, VPC endpoints SG, 6 VPC endpoints, 4 security group rules

**Next step:** Run the **state remove** commands in the **novaura-acs-processor** app repo (see list below). Do **not** run `terraform apply` in acs_processor until after those `terraform state rm` commands. Then remove the shared resource config from acs_processor and add variables/SSM for vpc_id, subnets, and vpc_endpoints_security_group_id.

**Dev** networking remains data-source-only (reads the same VPC/endpoints; does not own them). Only prod state owns the shared resources.

---

## Resources to remove from acs_processor state

Run these **in the novaura-acs-processor app repo**, from the directory where you run Terraform (e.g. the repo root or its `terraform/` folder), with `AWS_PROFILE=terraform-deployer`. Remove in this order (rules first, then endpoints, then SG, then NAT, then EIP):

| # | Terraform state address | Description |
|---|--------------------------|-------------|
| 1 | `aws_security_group_rule.vpc_endpoints_from_ecs` | Ingress 443 from ACS ECS service SG |
| 2 | `aws_security_group_rule.vpc_endpoints_from_link_runtime` | Ingress 443 from link-runtime ECS SG |
| 3 | `aws_security_group_rule.vpc_endpoints_ingress["sg-0b5dace630b2921f4"]` | Ingress 443 (additional SG) |
| 4 | `aws_security_group_rule.vpc_endpoints_ingress["sg-0d53d6ae130b321b5"]` | Ingress 443 (additional SG) |
| 5 | `aws_vpc_endpoint.secretsmanager` | Secrets Manager interface endpoint |
| 6 | `aws_vpc_endpoint.rds` | RDS interface endpoint |
| 7 | `aws_vpc_endpoint.logs` | CloudWatch Logs interface endpoint |
| 8 | `aws_vpc_endpoint.ecr_api` | ECR API interface endpoint |
| 9 | `aws_vpc_endpoint.ecr_dkr` | ECR DKR interface endpoint |
| 10 | `aws_vpc_endpoint.s3` | S3 gateway endpoint |
| 11 | `aws_security_group.vpc_endpoints` | VPC endpoints security group |
| 12 | `aws_nat_gateway.nat` | NAT gateway |
| 13 | `aws_eip.nat` | Elastic IP for NAT |

**Not in state:** `aws_route.nat_gateway` is not in acs_processor state (the route already existed, so `count` was 0). Nothing to remove for it.

**Copy-paste block** (run from acs_processor repo):

```bash
export AWS_PROFILE=terraform-deployer
# cd to the directory where you run terraform in the acs_processor repo

terraform state rm 'aws_security_group_rule.vpc_endpoints_from_ecs'
terraform state rm 'aws_security_group_rule.vpc_endpoints_from_link_runtime'
terraform state rm 'aws_security_group_rule.vpc_endpoints_ingress["sg-0b5dace630b2921f4"]'
terraform state rm 'aws_security_group_rule.vpc_endpoints_ingress["sg-0d53d6ae130b321b5"]'
terraform state rm aws_vpc_endpoint.secretsmanager
terraform state rm aws_vpc_endpoint.rds
terraform state rm aws_vpc_endpoint.logs
terraform state rm aws_vpc_endpoint.ecr_api
terraform state rm aws_vpc_endpoint.ecr_dkr
terraform state rm aws_vpc_endpoint.s3
terraform state rm aws_security_group.vpc_endpoints
terraform state rm aws_nat_gateway.nat
terraform state rm aws_eip.nat
```

---

## Current State: No Impact on Deployed Resources

**The shared networking stack in this repo (prod) now manages the NAT, VPC endpoints, and their security group** after the import. Dev stack still uses data sources only. It only:

| What the shared stack does | Effect on existing resources |
|----------------------------|------------------------------|
| **Data sources** (VPC, subnets, route table, existing Secrets Manager VPC endpoint) | Read-only. No changes to AWS. |
| **Optional** `aws_security_group_rule` (when `allowed_ecs_security_group_ids` is set) | Adds new ingress rules to the **existing** VPC endpoint SG. Only runs when you add SG IDs to the variable; with an empty list, nothing is created. |
| **Optional** `aws_ssm_parameter` (when `publish_to_ssm = true`) | Creates SSM parameters. Does not touch VPC/NAT/endpoints. |

So:

- **Nothing is destroyed or replaced.** The NAT gateway, EIP, all VPC endpoints (Secrets Manager, RDS, Logs, ECR API, ECR DKR, S3), and the VPC endpoint security group remain exactly as they are.
- **Ownership is still in acs_processor.** Those resources are still in the **acs_processor** Terraform state (in the acs_processor app repo, state key `ecs/terraform.tfstate`). This repo’s state does not own them.

The copy under `existing_terraforms/terraform-acs_processor/` is a reference. The **live** config and state that own the shared resources are in the **acs_processor application repository**. Until you complete the transfer steps below, do **not** remove the VPC/NAT/endpoint resources from the acs_processor config in that repo, or a later `terraform apply` there would plan to destroy them.

---

## Resources Currently Owned by acs_processor (to Transfer)

From `existing_terraforms/terraform-acs_processor/vpc.tf`, the resources that are shared and should eventually live in this repo’s state are:

| Terraform address (in acs_processor) | AWS resource | Identifiers / names |
|--------------------------------------|--------------|----------------------|
| `aws_eip.nat` | Elastic IP | Name: `novaura-acs-nat-eip` |
| `aws_nat_gateway.nat` | NAT Gateway | Name: `novaura-acs-nat-gateway` |
| `aws_route.nat_gateway` | Route (0.0.0.0/0 → NAT) | Route table + destination |
| `aws_security_group.vpc_endpoints` | Security group for endpoints | Name prefix: `novaura-acs-vpc-endpoints` |
| `aws_vpc_endpoint.secretsmanager` | Interface endpoint | Name: `novaura-acs-secretsmanager-endpoint` |
| `aws_vpc_endpoint.rds` | Interface endpoint | Name: `novaura-acs-rds-endpoint` |
| `aws_vpc_endpoint.logs` | Interface endpoint | Name: `novaura-acs-logs-endpoint` |
| `aws_vpc_endpoint.ecr_api` | Interface endpoint | Name: `novaura-acs-ecr-api-endpoint` |
| `aws_vpc_endpoint.ecr_dkr` | Interface endpoint | Name: `novaura-acs-ecr-dkr-endpoint` |
| `aws_vpc_endpoint.s3` | Gateway endpoint | Name: `novaura-acs-s3-endpoint` |
| `aws_security_group_rule.vpc_endpoints_from_ecs` | Ingress 443 from ECS SG | — |
| `aws_security_group_rule.vpc_endpoints_from_link_runtime` | Ingress 443 from link-runtime | — |
| `aws_security_group_rule.vpc_endpoints_ingress` (for_each) | Ingress 443 from tfvars list | — |

---

## Safe Transfer: Order of Operations

To move ownership to this repo **without destroying or replacing any deployed resources**:

1. **In this repo (shared networking stack)**  
   - Add Terraform **resource** definitions that match the existing resources (same configuration as in acs_processor: same subnets, route table, service names, tags, etc.).  
   - Run **import** for each resource into this repo’s state (e.g. `terraform import aws_eip.nat eip-xxxxx`), then `terraform plan` and fix any drift until plan is clean (no destroy, no unnecessary change).

2. **In the acs_processor app repo**  
   - **Remove** the shared resources from acs_processor state with `terraform state rm` (one by one) for:  
     `aws_eip.nat`, `aws_nat_gateway.nat`, `aws_route.nat_gateway`, `aws_security_group.vpc_endpoints`, each `aws_vpc_endpoint.*`, and each `aws_security_group_rule` that references the VPC endpoints SG.  
   - Do **not** run `terraform apply` in acs_processor between the imports in this repo and these `state rm` commands.  
   - Then remove the corresponding **config** from acs_processor (e.g. delete or trim `vpc.tf` and any references) and add variables/data or SSM for `vpc_id`, `private_subnet_ids`, `vpc_endpoints_security_group_id` so ECS and other resources keep working.

3. **Result**  
   - This repo’s state owns the NAT, endpoints, and SG.  
   - acs_processor’s state and config no longer reference them.  
   - No resources are destroyed or recreated; they are only reassigned from one state to the other.

**Critical:** Do **not** remove the resource blocks from acs_processor **before** importing them into this repo and then removing them from acs_processor state. If you remove the blocks first and then run `terraform apply` in acs_processor, Terraform will plan to **destroy** those resources.

---

## Summary

- **Current setup:** Our changes in the shared repo do not modify or delete any of the existing NAT/VPC endpoint/SG resources. They are still owned and managed by acs_processor’s state in the app repo.
- **Proper transfer:** Import those resources into this repo’s networking state first, then `state rm` them from acs_processor, then remove the resource definitions from acs_processor and switch it to using variables/SSM for VPC and endpoint SG. That sequence keeps all deployed resources intact while moving ownership to this repository.
