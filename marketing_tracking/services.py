from django.db import transaction
from django.utils import timezone
from .models import MarketingAttribution, IdentityGraph, IdentityNode, LeadIdentityMapping


class MarketingTrackingService:
    @staticmethod
    def capture_marketing_data(lead, request_data):
        """
        Capture marketing attribution data from a request and create a MarketingAttribution instance.
        """
        try:
            marketing_data = {
                'utm_source': request_data.get('utm_source'),
                'utm_medium': request_data.get('utm_medium'),
                'utm_campaign': request_data.get('utm_campaign'),
                'utm_content': request_data.get('utm_content'),
                'utm_term': request_data.get('utm_term'),
                'referrer': request_data.get('referrer'),
                'landing_page': request_data.get('landing_page'),
                'device_type': request_data.get('device_type'),
                'browser': request_data.get('browser'),
                'operating_system': request_data.get('operating_system'),
                'visitor_id': request_data.get('visitor_id'),
                'session_id': request_data.get('session_id'),
            }
            
            # Create marketing attribution record
            attribution = MarketingAttribution.objects.create(
                lead=lead,
                **marketing_data
            )
            
            return attribution
        except Exception as e:
            print(f"Error capturing marketing data: {str(e)}")
            return None

    @staticmethod
    def get_attribution_analysis(lead):
        """
        Analyze marketing attribution data for a lead.
        """
        attributions = MarketingAttribution.objects.filter(lead=lead).order_by('first_seen_at')
        
        if not attributions.exists():
            return None
            
        first_touch = attributions.first()
        last_touch = attributions.last()
        
        return {
            'first_touch': {
                'source': first_touch.utm_source,
                'medium': first_touch.utm_medium,
                'campaign': first_touch.utm_campaign,
                'timestamp': first_touch.first_seen_at,
            },
            'last_touch': {
                'source': last_touch.utm_source,
                'medium': last_touch.utm_medium,
                'campaign': last_touch.utm_campaign,
                'timestamp': last_touch.last_seen_at,
            },
            'total_touches': attributions.count(),
            'distinct_sources': attributions.values('utm_source').distinct().count(),
            'distinct_campaigns': attributions.values('utm_campaign').distinct().count(),
        }


class IdentityResolutionService:
    @staticmethod
    @transaction.atomic
    def create_or_get_identity_graph():
        """
        Create a new identity graph node.
        """
        return IdentityGraph.objects.create()

    @staticmethod
    @transaction.atomic
    def link_lead_to_identity(lead, identifier_type, identifier_value, confidence_score=1.0):
        """
        Link a lead to an identity graph node based on an identifier.
        If no identity graph exists for this identifier, create a new one.
        """
        try:
            # First, try to find an existing identity node with this identifier
            existing_node = IdentityNode.objects.filter(
                identifier_type=identifier_type,
                identifier_value=identifier_value
            ).first()

            if existing_node:
                # If we found an existing node, use its identity graph
                identity_graph = existing_node.identity_graph
            else:
                # If no existing node, create a new identity graph
                identity_graph = IdentityResolutionService.create_or_get_identity_graph()
                
                # Create a new identity node
                IdentityNode.objects.create(
                    identity_graph=identity_graph,
                    identifier_type=identifier_type,
                    identifier_value=identifier_value,
                    confidence_score=confidence_score
                )

            # Create or update the lead mapping
            mapping, created = LeadIdentityMapping.objects.get_or_create(
                lead=lead,
                identity_graph=identity_graph,
                defaults={'confidence_score': confidence_score}
            )

            return mapping, created

        except Exception as e:
            print(f"Error linking lead to identity: {str(e)}")
            return None, False

    @staticmethod
    def get_related_leads(lead):
        """
        Get all leads that share identity nodes with the given lead.
        """
        try:
            # Get the identity graph for this lead
            mapping = LeadIdentityMapping.objects.filter(lead=lead).first()
            if not mapping:
                return []

            # Get all leads mapped to the same identity graph
            related_mappings = LeadIdentityMapping.objects.filter(
                identity_graph=mapping.identity_graph
            ).exclude(lead=lead)

            return [mapping.lead for mapping in related_mappings]

        except Exception as e:
            print(f"Error getting related leads: {str(e)}")
            return []

    @staticmethod
    @transaction.atomic
    def merge_identity_graphs(graph1, graph2, confidence_score=0.8):
        """
        Merge two identity graphs when we're confident they represent the same entity.
        """
        try:
            # Move all nodes from graph2 to graph1
            IdentityNode.objects.filter(identity_graph=graph2).update(identity_graph=graph1)
            
            # Move all lead mappings from graph2 to graph1
            LeadIdentityMapping.objects.filter(identity_graph=graph2).update(identity_graph=graph1)
            
            # Delete the now-empty graph2
            graph2.delete()
            
            return True
        except Exception as e:
            print(f"Error merging identity graphs: {str(e)}")
            return False

    @staticmethod
    def get_identity_graph_for_lead(lead):
        """
        Get the identity graph for a lead.
        """
        try:
            mapping = LeadIdentityMapping.objects.filter(lead=lead).first()
            return mapping.identity_graph if mapping else None
        except Exception as e:
            print(f"Error getting identity graph for lead: {str(e)}")
            return None


class CTAUIDService:
    """
    Service for generating and managing CTA UIDs for ISCI generation.
    
    UID Format: Prefix-based with 4 digits
    - T0001, T0002, ... (Toll-Free Numbers)
    - K0001, K0002, ... (Keywords)
    - U0001, U0002, ... (URL Domains)
    
    Scalability: 10,000 UIDs per type = 30,000 total CTAs
    """
    
    # Prefix mapping for CTA types
    PREFIX_MAP = {
        'toll_free': 'T',
        'keyword': 'K',
        'url_domain': 'U',
    }
    
    # UID length (excluding prefix)
    UID_LENGTH = 4  # Can be increased to 6 for more scalability
    
    @classmethod
    @transaction.atomic
    def generate_uid(cls, cta_type, model_instance=None):
        """
        Generate a unique CTA UID for ISCI generation.
        
        Args:
            cta_type: One of 'toll_free', 'keyword', 'url_domain'
            model_instance: Optional model instance to exclude from uniqueness check
        
        Returns:
            str: Unique CTA UID (e.g., 'T0001', 'K0001', 'U0001')
        """
        prefix = cls.PREFIX_MAP.get(cta_type)
        if not prefix:
            raise ValueError(f"Invalid CTA type: {cta_type}. Must be one of {list(cls.PREFIX_MAP.keys())}")
        
        # Import here to avoid circular imports
        from .models import TollFreeNumber, Keyword, URLDomain
        
        # Get the appropriate model
        model_map = {
            'toll_free': TollFreeNumber,
            'keyword': Keyword,
            'url_domain': URLDomain,
        }
        model_class = model_map[cta_type]
        
        # Find the highest existing UID for this type
        existing_uids = model_class.objects.exclude(
            cta_uid__isnull=True
        ).exclude(
            cta_uid=''
        )
        
        if model_instance and model_instance.pk:
            existing_uids = existing_uids.exclude(pk=model_instance.pk)
        
        # Extract numeric parts from existing UIDs
        max_num = 0
        for instance in existing_uids:
            if instance.cta_uid and instance.cta_uid.startswith(prefix):
                try:
                    num_part = instance.cta_uid[len(prefix):]
                    num = int(num_part)
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    continue
        
        # Generate next UID
        next_num = max_num + 1
        
        # Check if we've exceeded the limit
        max_possible = 10 ** cls.UID_LENGTH - 1
        if next_num > max_possible:
            raise ValueError(
                f"UID limit reached for {cta_type}. Maximum {max_possible} UIDs allowed. "
                f"Consider increasing UID_LENGTH or using alphanumeric format."
            )
        
        # Format with leading zeros
        uid = f"{prefix}{next_num:0{cls.UID_LENGTH}d}"
        
        # Double-check uniqueness (race condition protection)
        if model_class.objects.filter(cta_uid=uid).exclude(
            pk=model_instance.pk if model_instance and model_instance.pk else None
        ).exists():
            # If collision, try next number
            return cls.generate_uid(cta_type, model_instance)
        
        return uid
    
    @classmethod
    def validate_uid_format(cls, uid):
        """
        Validate that a UID matches the expected format.
        
        Args:
            uid: UID string to validate
        
        Returns:
            bool: True if valid, False otherwise
        """
        if not uid or len(uid) != cls.UID_LENGTH + 1:
            return False
        
        prefix = uid[0]
        if prefix not in cls.PREFIX_MAP.values():
            return False
        
        try:
            int(uid[1:])
            return True
        except ValueError:
            return False