import type { INodeProperties } from 'n8n-workflow';

export const queryOperationFields: INodeProperties[] = [
	{
		displayName: 'Dataset ID',
		name: 'datasetId',
		type: 'string',
		default: '',
		required: true,
		placeholder: 'ds_01HXXXX...',
		description: 'ID of the dataset to query',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['query'],
			},
		},
	},
	{
		displayName: 'Query',
		name: 'query',
		type: 'string',
		default: '',
		required: true,
		typeOptions: {
			rows: 3,
		},
		description: 'Natural-language question to send to the RAG pipeline',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['query'],
			},
		},
	},
	{
		displayName: 'Top K',
		name: 'topK',
		type: 'number',
		default: 5,
		typeOptions: {
			minValue: 1,
			maxValue: 50,
		},
		description: 'Number of chunks to retrieve from the vector store',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['query'],
			},
		},
	},
	{
		displayName: 'Additional Options',
		name: 'additionalOptions',
		type: 'collection',
		placeholder: 'Add option',
		default: {},
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['query'],
			},
		},
		options: [
			{
				displayName: 'Plugin',
				name: 'plugin',
				type: 'string',
				default: '',
				description:
					'Optional frontend plugin name to override default answer formatting',
			},
			{
				displayName: 'Filters (JSON)',
				name: 'filters',
				type: 'json',
				default: '{}',
				description: 'Metadata filters applied to retrieval',
			},
		],
	},
];
