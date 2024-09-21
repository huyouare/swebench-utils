import json

def filter_instances(input_file, output_file):
    # Read instance IDs from @all_preds.jsonl
    instance_ids = set()
    with open('20240824_gru/all_preds.jsonl', 'r') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                instance_ids.add(data['instance_id'])

    # Filter and write matching instances
    with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
        for line in infile:
            if line.strip():
                data = json.loads(line)
                if data['instance_id'] in instance_ids:
                    outfile.write(line)

    print(f"Filtered instances have been written to {output_file}")

# Usage
input_file = '20240820_honeycomb/all_preds_full.jsonl'
output_file = 'filtered_instances.jsonl'
filter_instances(input_file, output_file)
