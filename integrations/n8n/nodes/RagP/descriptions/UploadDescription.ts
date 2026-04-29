import type { INodeProperties } from 'n8n-workflow';

export const uploadOperationFields: INodeProperties[] = [
	{
		displayName: 'Dataset ID',
		name: 'datasetId',
		type: 'string',
		default: '',
		required: true,
		placeholder: 'ds_01HXXXX...',
		description: 'ID of the dataset to upload the document into',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['uploadDocument'],
			},
		},
	},
	{
		displayName: 'Input Type',
		name: 'inputType',
		type: 'options',
		default: 'text',
		options: [
			{
				name: 'Text',
				value: 'text',
				description: 'Send a plain-text payload',
			},
			{
				name: 'Binary',
				value: 'binary',
				description: 'Send a binary file from the previous node',
			},
		],
		description: 'How the document content is provided',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['uploadDocument'],
			},
		},
	},
	{
		displayName: 'Text Content',
		name: 'textContent',
		type: 'string',
		default: '',
		required: true,
		typeOptions: {
			rows: 6,
		},
		description: 'Document body as plain text',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['uploadDocument'],
				inputType: ['text'],
			},
		},
	},
	{
		displayName: 'Binary Property',
		name: 'binaryPropertyName',
		type: 'string',
		default: 'data',
		required: true,
		description:
			'Name of the binary property on the input item that holds the file to upload',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['uploadDocument'],
				inputType: ['binary'],
			},
		},
	},
	{
		displayName: 'Filename',
		name: 'filename',
		type: 'string',
		default: '',
		description: 'Optional display name for the document. Defaults to the binary file name or "document.txt".',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['uploadDocument'],
			},
		},
	},
];
