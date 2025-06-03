#!/bin/bash

# Get the current commit SHA
COMMIT_SHA=$(git rev-parse HEAD)

# Ensure we're in the terraform directory
cd terraform

# Initialize Terraform
terraform init -reconfigure

# Apply with the specific image tag
terraform apply -var="image_tag=$COMMIT_SHA" "$@" 