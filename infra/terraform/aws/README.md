# Terraform — AWS infrastructure for smart-fleet

> **Status: tested against a local AWS emulator (Moto) only. This module has never been applied to a real AWS account.**

This module describes the AWS infrastructure needed to run the smart-fleet stack on a single EC2 instance:

| Resource | Purpose |
|---|---|
| `aws_vpc` | Isolated network `10.0.0.0/16` |
| `aws_subnet` (public) | `10.0.1.0/24`, instances get a public IP |
| `aws_internet_gateway` + `aws_route_table` | Outbound/inbound internet routing for the public subnet |
| `aws_security_group` + rules | Ports **22, 8000, 3000 only**, and only from `allowed_cidrs` (`0.0.0.0/0` is rejected by validation) |
| `aws_instance` (`t3.micro`) | Ubuntu 24.04, IMDSv2 required, encrypted root volume |
| `user_data` (cloud-init) | On first boot clones this repo and runs the [Ansible playbook](../../../deploy/ansible) against `localhost` |

Terraform creates the machine; Ansible (via cloud-init) configures what runs on it. The Grafana admin password is generated on the instance at boot, so it never appears in `user_data` or the Terraform state.

## How it is tested

[Moto](https://github.com/getmoto/moto) is an open-source (MIT) AWS emulator. With `use_local_emulator = true` the AWS provider sends every API call to Moto with fake credentials (`test`/`test`), so no AWS account, credit card or token is needed.

The `terraform` job in CI runs:

1. `terraform fmt -check`, `terraform validate`, `tflint` (with the AWS ruleset)
2. Moto as a service container
3. `terraform plan` → `apply` → check outputs → `plan` again (must show no changes) → `destroy`

**What this proves:** the configuration is valid, the resources and their dependencies can be created and destroyed through the AWS API, and outputs are wired correctly.

**What this does not prove:** Moto only *simulates* the API. No virtual machine is started, `user_data` is never executed, and networking/security group behaviour is not enforced. Moto also has no Ubuntu 24.04 AMI, so `emulator.tfvars` uses one of Moto's built-in Ubuntu AMIs.

## Run locally against Moto

```bash
docker run -d --name moto -p 5000:5000 motoserver/moto:5.2.3
cd infra/terraform/aws
terraform init
terraform apply -var-file=emulator.tfvars
terraform output
terraform destroy -var-file=emulator.tfvars
docker rm -f moto
```

On macOS port 5000 is often taken by AirPlay Receiver; map Moto to another port (e.g. `-p 5001:5000`) and pass `-var=emulator_endpoint=http://localhost:5001`.

## Applying to real AWS (not done)

Would require AWS credentials and a tfvars file such as:

```hcl
allowed_cidrs = ["<your-public-ip>/32"]
image_tag     = "sha-1a2b3c4"
key_name      = "<existing-key-pair>"
```

For a real setup the state should live in a remote backend (e.g. S3 with state locking) instead of a local `terraform.tfstate` file.

## Inputs

| Name | Default | Description |
|---|---|---|
| `aws_region` | `eu-central-1` | AWS region |
| `instance_type` | `t3.micro` | EC2 instance type |
| `allowed_cidrs` | – (required) | CIDRs allowed to reach 22/8000/3000; `0.0.0.0/0` rejected |
| `image_tag` | – (required) | Immutable GHCR image tag; `latest` rejected |
| `ami_id` | `null` | AMI override; when null, latest Canonical Ubuntu 24.04 |
| `key_name` | `null` | Existing EC2 key pair for SSH |
| `repo_url` / `repo_ref` | this repo / `main` | Repository cloned by cloud-init |
| `use_local_emulator` | `false` | Point the provider at a local emulator |
| `emulator_endpoint` | `http://localhost:5000` | Emulator URL |

## Outputs

`instance_id`, `public_ip`, `api_url`, `grafana_url`, `security_group_id`
