#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path

def read_env_file(env_path):
    """Read .env file and return a dictionary of key-value pairs."""
    env_vars = {}
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars

def is_list_value(value):
    """Check if the value is a list format."""
    value = value.strip()
    return value.startswith('[') and value.endswith(']')

def is_json_value(value):
    """Check if the value is a JSON format."""
    value = value.strip()
    return (value.startswith('{') and value.endswith('}')) or \
           (value.startswith('[') and value.endswith(']'))

def convert_value(value):
    """Convert value to appropriate format."""
    value = value.strip()
    
    # Handle empty values
    if not value:
        return '""'
    
    # Handle list values
    if is_list_value(value):
        try:
            # Try to parse as JSON to validate
            json.loads(value)
            return value
        except json.JSONDecodeError:
            # If not valid JSON, treat as string
            return f'"{value}"'
    
    # Handle JSON values
    if is_json_value(value):
        try:
            # Try to parse as JSON to validate
            json.loads(value)
            return value
        except json.JSONDecodeError:
            # If not valid JSON, treat as string
            return f'"{value}"'
    
    # Handle boolean values
    if value.lower() in ('true', 'false'):
        return value.lower()
    
    # Handle numeric values
    try:
        float(value)
        return value
    except ValueError:
        pass
    
    # Default to string
    return f'"{value}"'

def convert_to_tfvars(env_vars):
    """Convert environment variables to terraform.tfvars format."""
    # Convert all keys to lowercase and replace underscores
    tfvars = {}
    for key, value in env_vars.items():
        # Convert key to terraform variable format
        tf_key = key.lower()
        tfvars[tf_key] = convert_value(value)
    
    # Format the output with proper alignment
    max_key_length = max(len(key) for key in tfvars.keys())
    output = []
    
    for key, value in sorted(tfvars.items()):
        # Don't add quotes for boolean, numeric, or JSON values
        if value.startswith('"') or value.startswith('[') or value.startswith('{'):
            output.append(f'{key:<{max_key_length}} = {value}')
        else:
            output.append(f'{key:<{max_key_length}} = {value}')
    
    return '\n'.join(output)

def main():
    # Get the .env file path from command line or use default
    env_path = sys.argv[1] if len(sys.argv) > 1 else '.env'
    
    if not os.path.exists(env_path):
        print(f"Error: {env_path} file not found")
        sys.exit(1)
    
    # Read and convert
    env_vars = read_env_file(env_path)
    tfvars_content = convert_to_tfvars(env_vars)
    
    # Write to terraform.tfvars
    output_path = 'terraform/terraform.tfvars'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w') as f:
        f.write(tfvars_content)
    
    print(f"Successfully converted {env_path} to {output_path}")

if __name__ == '__main__':
    main() 