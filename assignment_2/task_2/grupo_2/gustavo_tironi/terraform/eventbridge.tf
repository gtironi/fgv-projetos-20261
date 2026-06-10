# ==========================================================================
# EventBridge — agenda execuções automáticas do Glue job incremental.
#
# IAM: usa local.glue_role_arn (LabRole, já definido em main.tf), sem criar
# role nova — não é permitido no AWS Academy. LabRole é confiável (trust
# policy) por Glue/Lambda; pode não ser por events.amazonaws.com. Se o
# `apply` deste arquivo falhar com erro de IAM/AssumeRole, esse é o motivo
# esperado — ver README para o fallback.
# ==========================================================================

resource "aws_cloudwatch_event_rule" "weekly_etl" {
  name                = "classicmodels-etl-weekly"
  description         = "Dispara o Glue job incremental semanalmente"
  schedule_expression = "cron(0 12 ? * MON *)"
}

resource "aws_cloudwatch_event_target" "glue_job" {
  rule     = aws_cloudwatch_event_rule.weekly_etl.name
  arn      = aws_glue_job.etl.arn
  role_arn = local.glue_role_arn

  glue_parameters {
    job_name = aws_glue_job.etl.name
  }
}
