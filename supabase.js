import { createClient } from '@supabase/supabase-js';

export const supabase = createClient(
  'https://idygvqhdzjpjyqxbftxj.supabase.co',
  'sb_publishable_9RG1FwiODqJ0MUPoDERpzQ_F552c8BN'
);

export const API = 'https://cbk-analytics-backend.onrender.com/api';
