# Terraform ownership and transfer (acs_processor app repo)

This document records the transfer of **shared networking resources** from this app repo to the **main/shared Terraform repo**.

---

## Status

| Step | Status |
|------|--------|
| **Import in main repo** | ✅ Complete — shared resources were imported into the main Terraform project’s state. |
| **State remove in acs_processor** | ✅ Complete — all 13 state addresses were removed from this repo’s state (see below). |
| **Config removal in acs_processor** | ✅ Complete — shared resource definitions were removed from `vpc.tf`; this repo now uses **variables** for `vpc_id`, `private_subnet_ids`, `public_subnet_ids`, and `vpc_endpoints_security_group_id`. |

**Next step (if applicable):** In the main repo, ensure `terraform plan` is clean after the imports. In this repo, run `terraform plan` / `terraform apply` as needed; no further state rm or config changes are required for the transfer.

---

## What was removed from acs_processor state

Removed in this order (rules first, then endpoints, then SG, then NAT, then EIP):

1. `aws_security_group_rule.vpc_endpoints_from_ecs`
2. `aws_security_group_rule.vpc_endpoints_from_link_runtime`
3. `aws_security_group_rule.vpc_endpoints_ingress["sg-0b5dace630b2921f4"]`
4. `aws_security_group_rule.vpc_endpoints_ingress["sg-0d53d6ae130b321b5"]`
5. `aws_vpc_endpoint.secretsmanager`
6. `aws_vpc_endpoint.rds`
7. `aws_vpc_endpoint.logs`
8. `aws_vpc_endpoint.ecr_api`
9. `aws_vpc_endpoint.ecr_dkr`
10. `aws_vpc_endpoint.s3`
11. `aws_security_group.vpc_endpoints`
12. `aws_nat_gateway.nat`
13. `aws_eip.nat`

**Not in state:** `aws_route.nat_gateway` was never in acs_processor state (route already existed, so `count` was 0).

---

## How this repo gets VPC/subnet/SG values now

- **Variables** (see `terraform/main.tf` and `terraform/terraform.tfvars`):  
  `vpc_id`, `private_subnet_ids`, `public_subnet_ids`, `vpc_endpoints_security_group_id`
- Values can be set in `terraform.tfvars` or, in the future, from **SSM** (e.g. data source or pipeline).
- The **main Terraform repo** owns and manages the NAT gateway, VPC endpoints, and VPC endpoints security group; this repo only consumes their IDs.

---

## Reference

- Migration identifiers and commands: [terraform-migration-to-shared-repo.md](./terraform-migration-to-shared-repo.md)
