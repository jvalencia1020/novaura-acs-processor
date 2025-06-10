#!/bin/bash

# Get the current commit SHA
COMMIT_SHA=$(git rev-parse HEAD)

# Ensure we're in the terraform directory
cd terraform

# Apply with the specific image tag
AWS_PROFILE=terraform-deployer terraform apply -var="image_tag=$COMMIT_SHA" "$@" 