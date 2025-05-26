# Auto-scaling for Journey Worker
resource "aws_appautoscaling_target" "journey_worker_target" {
  max_capacity       = 0
  min_capacity       = 0
  resource_id        = "service/${aws_ecs_cluster.processor_cluster.name}/${aws_ecs_service.journey_worker_service.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "journey_worker_policy" {
  name               = "novaura-acs-journey-worker-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.journey_worker_target.resource_id
  scalable_dimension = aws_appautoscaling_target.journey_worker_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.journey_worker_target.service_namespace
  
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300  # 5 minutes
    scale_out_cooldown = 60   # 1 minute
  }
}

# Auto-scaling for Bulk Campaign Worker
resource "aws_appautoscaling_target" "bulk_campaign_worker_target" {
  max_capacity       = 0
  min_capacity       = 0
  resource_id        = "service/${aws_ecs_cluster.processor_cluster.name}/${aws_ecs_service.bulk_campaign_worker_service.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "bulk_campaign_worker_policy" {
  name               = "novaura-acs-bulk-campaign-worker-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.bulk_campaign_worker_target.resource_id
  scalable_dimension = aws_appautoscaling_target.bulk_campaign_worker_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.bulk_campaign_worker_target.service_namespace
  
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300  # 5 minutes
    scale_out_cooldown = 60   # 1 minute
  }
} 