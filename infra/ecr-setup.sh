#!/bin/bash
# ── Create ECR repository (run once from your local machine) ──────────────────
# Requires AWS CLI configured with admin permissions.

AWS_REGION=${1:-us-east-1}
REPO_NAME=schoolbot

echo "▶ Creating ECR repository '$REPO_NAME' in $AWS_REGION..."

aws ecr create-repository \
  --repository-name $REPO_NAME \
  --region $AWS_REGION \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256

echo "✅ ECR repository created."
echo ""
echo "Add this to your GitHub repository secrets:"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "  ECR_REGISTRY: ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
echo "  ECR_REPOSITORY: $REPO_NAME"
